# -*- coding: utf-8 -*-
"""答案生成节点 — 组装 Prompt → LLM 流式生成 → SSE 推送

相比课程版的修复：
1. 删除三处错误 import（multiprocessing.connection / mcp / modelscope），
   SSEEvent 统一来自 sse_utils（线程队列版）
2. _step3 原版 `for i, doc in enumerate('content')` 遍历字符串字面量 →
   改为遍历 docs，且去掉循环内提前 return
3. _format_chat_history 原版把 formatted_lines 覆盖成字符串再 .append
   （直接 AttributeError）→ 改为 line 变量 + append
4. 生成的答案原版只存局部变量、从未回写 state（历史落库永远不触发）→
   现回写 {prompt, answer, image_urls}
5. _step4 落库改为显式传入 final_text（mongo_history_utils 在 kb-platform
   下为 no-op 兼容层，真实落库由 chat 服务 persist_log 完成）
"""
import re
from typing import Dict, List, Tuple

from app.engine.query_process.base import NodeBase
from app.engine.query_process.prompt import ANSWER_PROMPT, PERMISSION_BLOCKED_ANSWER
from app.engine.query_process.state import QueryGraphState
from app.engine.tool.logger import logger
from app.engine.utils.llm_utils import get_llm_client
from app.engine.utils.mongo_history_utils import save_chat_message
from app.engine.utils.sse_utils import SSEEvent, push_sse_event


class NodeAnswerOutput(NodeBase):
    """答案生成：反问直出 / 权限拦截提示 / 检索后 LLM 流式生成"""

    name: str = "node_answer_output"
    MAX_CONTEXT_CHARS = 12000  # 参考内容字符预算
    BLOCKED_PROBE_SCORE_MIN = 0.30  # 与 NodeRerank.SCORE_MIN 一致

    def process(self, state: QueryGraphState) -> QueryGraphState:
        task_id = state.get("task_id")
        answer = state.get("answer")

        # 分支一：上游已生成答案（反问/澄清），直接推送
        if answer:
            push_sse_event(task_id, SSEEvent.FINAL, {
                "answer": answer, "image_urls": [],
            })
            return {}

        # 分支二：检索无结果 → 权限拦截探测（相关内容存在但被权限过滤）
        if not (state.get("reranked_docs") or []):
            blocked_doc_ids = self._probe_blocked_docs(state)
            if blocked_doc_ids:
                answer = PERMISSION_BLOCKED_ANSWER
                logger.info("权限拦截：检索无结果但存在 %d 份无权访问的相关文档", len(blocked_doc_ids))
                push_sse_event(task_id, SSEEvent.FINAL, {
                    "answer": answer, "image_urls": [],
                })
                return {"answer": answer, "blocked_doc_ids": blocked_doc_ids}

        # 分支三：正常检索链路 → 组装 Prompt → 流式生成
        prompt = self._step1_construct_prompt(state)

        final_text = self._step2_generate_response(state, prompt)
        image_urls = self._step3_extract_image_from_docs(state.get("reranked_docs"))

        # 落库（kb-platform 下为 no-op，真实落库由 chat 服务完成）
        self._step4_write_history(state, answer=final_text, image_urls=image_urls)

        # 结束事件：携带完整答案 + 图片（前端可不强依赖 delta 累加）
        push_sse_event(task_id, SSEEvent.FINAL, {
            "answer": final_text, "image_urls": image_urls,
        })
        return {"prompt": prompt, "answer": final_text, "image_urls": image_urls}

    # ------------------------------------------------------------------
    def _probe_blocked_docs(self, state) -> List[str]:
        """检索无结果时探测：去掉权限过滤重检索，确认相关内容是否因权限被拦截

        复用检索节点的混合检索（保留 item_name 过滤、去掉 perm_expr），
        再 rerank 打分——最高分达到入选线说明"内容存在且相关，只是无权访问"。
        返回相关且无权访问的文档 doc_id 列表；探测失败按无拦截处理（降级到原链路）。
        """
        if not state.get("perm_expr"):
            return []  # 未启用权限过滤的调用谈不上拦截
        query = state.get("rewritten_query") or state.get("original_query")
        if not query:
            return []
        try:
            from app.engine.query_process.nodes.node_search_embedding import NodeSearchEmbedding
            from app.engine.utils.reranker_http_utils import rerank_documents

            candidates = NodeSearchEmbedding()._step2_search_embedding(
                rewritten_query=query,
                item_names=state.get("item_names") or [],
                perm_expr=None,
            )
            if not candidates:
                return []

            contents = [c.get("content") or "" for c in candidates]
            scores = rerank_documents(query, contents)
            ranked = sorted(zip(candidates, scores), key=lambda x: -float(x[1]))

            blocked, seen = [], set()
            for doc, score in ranked:
                if float(score) < self.BLOCKED_PROBE_SCORE_MIN:
                    break
                doc_id = doc.get("doc_id")
                if doc_id and doc_id not in seen:
                    seen.add(doc_id)
                    blocked.append(doc_id)
            return blocked
        except Exception as e:  # noqa: BLE001
            logger.warning("权限拦截探测失败（按无拦截处理）：%s", e)
            return []

    def _step1_construct_prompt(self, state) -> str:
        """组装提示词：参考内容 + 历史 + 主体名 + 问题"""
        char_budget = self.MAX_CONTEXT_CHARS

        question = state.get("rewritten_query") or state.get("original_query")
        item_names = state.get("item_names") or []

        context_str, char_budget = self._format_reranked_docs(
            state.get("reranked_docs") or [], char_budget)
        history_str, char_budget = self._format_chat_history(
            state.get("history") or [], char_budget)
        item_names_str = ",".join(item_names) if item_names else "无指定主体"

        return ANSWER_PROMPT.format(
            context=context_str or "无参考内容",
            history=history_str or "暂无历史对话",
            item_names=item_names_str,
            question=question,
        )

    def _format_reranked_docs(self, reranked_docs: List[Dict],
                              char_budget: int) -> Tuple[str, int]:
        """格式化重排序文档，带字符预算控制；编号 [N] 与提示词 [片段N] 对应"""
        formatted_lines: List[str] = []
        used_chars = 0
        for idx, doc in enumerate(reranked_docs, start=1):
            content = doc.get("content")
            if not content:
                continue

            meta_tags = [f"[{idx}]"]
            for field, template in [
                ("source", "[source={}]"),
                ("chunk_id", "[chunk_id={}]"),
                ("doc_id", "[doc_id={}]"),
                ("url", "[url={}]"),
                ("title", "[title={}]"),
            ]:
                field_value = str(doc.get(field) or "").strip()
                if field_value and field_value != "None":
                    meta_tags.append(template.format(field_value))
            score = doc.get("score")
            if score is not None:
                meta_tags.append(f"[score={float(score):.4f}]")

            doc_entry = " ".join(meta_tags) + "\n" + content
            if used_chars + len(doc_entry) > char_budget:
                break
            formatted_lines.append(doc_entry)
            used_chars += len(doc_entry) + 2
        return "\n\n".join(formatted_lines), char_budget - used_chars

    def _format_chat_history(self, chat_history: List[Dict],
                             char_budget: int) -> Tuple[str, int]:
        """格式化历史对话（原版字符串覆盖 bug 已修复）"""
        formatted_lines: List[str] = []
        used_chars = 0
        role_label_map = {"user": "用户", "assistant": "助手"}
        for message in chat_history:
            role = message.get("role", "")
            text = message.get("text", "")
            if not text or role not in role_label_map:
                continue

            line = f"{role_label_map[role]}:{text}"
            if used_chars + len(line) + 1 > char_budget:
                break
            formatted_lines.append(line)
            used_chars += len(line) + 1
        return "\n".join(formatted_lines), char_budget - used_chars

    def _step2_generate_response(self, state, prompt: str) -> str:
        """调用 LLM 流式生成，delta 实时推送 SSE"""
        llm = get_llm_client()
        task_id = state.get("task_id")
        final_text = ""

        try:
            for chunk in llm.stream(prompt):
                delta = chunk.content
                if delta:
                    push_sse_event(task_id, SSEEvent.DELTA, {"delta": delta})
                    final_text += delta
        except Exception as e:  # noqa: BLE001
            push_sse_event(task_id, SSEEvent.ERROR, {"error": str(e)})
            logger.error("流式生成出错：%s", e, exc_info=True)
        return final_text

    def _step3_extract_image_from_docs(self, docs) -> List[str]:
        """从重排文档的 markdown 中提取图片 URL（去重保序）"""
        if not docs:
            return []
        md_img_pattern = re.compile(r"!\[.*?\]\((.*?)\)")
        images: List[str] = []
        seen = set()
        for doc in docs:
            text = doc.get("content") or ""
            for img_url in md_img_pattern.findall(text):
                img_url = img_url.strip()
                if img_url and img_url not in seen:
                    seen.add(img_url)
                    images.append(img_url)
        return images

    def _step4_write_history(self, state, answer: str, image_urls=None):
        """写入历史（kb-platform 下 no-op，落库由 persist_log 统一处理）"""
        try:
            if answer:
                save_chat_message(
                    session_id=state.get("session_id"),
                    role="assistant",
                    text=answer,
                    rewritten_query="",
                    item_names=state.get("item_names") or [],
                    image_urls=image_urls,
                    message_id=None,
                )
        except Exception as e:  # noqa: BLE001
            logger.error("写入历史记录失败：%s", e)
