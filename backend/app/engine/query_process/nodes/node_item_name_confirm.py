# -*- coding: utf-8 -*-
"""主体确认节点 — 实体提取/改写 + 向量对齐 + 歧义反问

相比课程版：
1. 商品名泛化为文档主体（产品型号/制度名/项目代号），prompt 已泛化
2. Mongo 历史改走兼容层（SQLite 注入），session_id 不再强制校验
3. item_name 集合检索注入权限 expr——反问选项不得泄露无权文档的实体名
4. _step6 对齐逻辑修复：原版每个实体覆盖上一个的结果（continue 丢失累积），
   现按实体逐个累积确认/候选列表
5. 分支C（无匹配）不再阻断问答：企业知识库场景下实体未匹配应继续正常检索，
   而非直接拒绝（原"未找到相关产品"是商品域逻辑）
"""
import json
from typing import Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from app.engine.config.config import lm_config, milvus_config
from app.engine.query_process.base import NodeBase
from app.engine.query_process.prompt import (
    ITEM_NAME_EXTRACT_SYSTEM_PROMPT,
    ITEM_NAME_EXTRACT_TEMPLATE,
    PERMISSION_BLOCKED_ANSWER,
)
from app.engine.query_process.state import QueryGraphState
from app.engine.tool.logger import logger
from app.engine.utils.embedding_utils import generate_embeddings
from app.engine.utils.llm_utils import get_llm_client
from app.engine.utils.milvus_utils import create_hybrid_search_request, hybrid_search
from app.engine.utils.mongo_history_utils import get_recent_messages

# 对齐阈值：>0.85 直接确认；0.6~0.85 进候选（反问）；<0.6 忽略
ALIGN_CONFIRM_SCORE = 0.85
ALIGN_OPTION_SCORE = 0.6
ALIGN_OPTION_TOPN = 3


class NodeItemNameConfirm(NodeBase):
    """确认用户问题中的核心文档主体"""

    name: str = "node_item_name_confirm"

    def process(self, state: QueryGraphState):
        # 1. 参数（session_id 兼容 kb-platform 的整型 ID）
        original_query = state.get("original_query")
        if not original_query:
            raise ValueError("核心参数original_query缺失")
        session_id = str(state.get("session_id") or "kb")

        # 2. 历史对话（chat 服务注入）
        history = get_recent_messages(session_id)

        # 3. 提取主体名 + 改写问题（LLM）
        extract_result = self._step4_extract_info(original_query, history)
        item_names = extract_result.get("item_names") or []
        rewritten_query = extract_result.get("rewritten_query") or original_query

        # 4. 主体名向量对齐（确认 or 候选）
        align_result = {}
        if item_names:
            query_results = self._step5_vectorize_and_query(
                item_names, perm_expr=state.get("perm_expr"))
            align_result = self._step6_align_item_names(query_results)
        else:
            logger.info("未提取到主体名，跳过实体对齐")

        # 5. 确认状态检查（分支A继续检索 / 分支B反问 / 分支C无实体继续）
        dict_result = self._step7_check_confirmation(align_result)

        # 6. 权限拦截检测：对齐无确认（反问/无匹配）时无权限过滤重新对齐——
        #    强确认说明主体存在于受限文档，直接告知无权限，替代误导性反问
        if not dict_result.get("item_names") and state.get("perm_expr") and item_names:
            blocked_doc_ids = self._step8_probe_blocked_alignment(item_names)
            if blocked_doc_ids:
                logger.info("权限拦截（实体对齐）：主体存在但无权访问，涉及 %d 份文档",
                            len(blocked_doc_ids))
                return {
                    "history": history,
                    "rewritten_query": rewritten_query,
                    "item_names": [],
                    "answer": PERMISSION_BLOCKED_ANSWER,
                    "blocked_doc_ids": blocked_doc_ids,
                }

        return {
            "history": history,
            "rewritten_query": rewritten_query,
            "item_names": dict_result.get("item_names", []),
            "answer": dict_result.get("answer", ""),
        }

    def _step4_extract_info(self, original_query, history) -> Dict:
        try:
            history_text = ""
            for msg in reversed(history[-6:]):
                history_text += f"{msg.get('role')}: {msg.get('text')}\n"

            user_prompt = ITEM_NAME_EXTRACT_TEMPLATE.format(
                history_text=history_text or "（无）",
                original_query=original_query,
            )
            messages = [
                SystemMessage(content=ITEM_NAME_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]

            llm_client = get_llm_client(model=lm_config.item_model, json_mode=True)
            response = llm_client.invoke(messages)
            content = response.content

            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "")
            result = json.loads(content)

            result.setdefault("item_names", [])
            result.setdefault("rewritten_query", original_query)
            result["item_names"] = [
                n.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", "")
                for n in result["item_names"] if n
            ]
            return result
        except Exception as e:  # noqa: BLE001
            logger.exception("主体信息提取失败：%s", e)
            return {"item_names": [], "rewritten_query": original_query}

    def _step5_vectorize_and_query(self, item_names, perm_expr=None) -> List[Dict]:
        """主体名 → 双向量 → item_name 集合混合检索（权限过滤）"""
        embeddings = generate_embeddings(item_names)
        dense_vectors = embeddings["dense"]
        sparse_vectors = embeddings["sparse"]

        results = []
        for i, item_name in enumerate(item_names):
            try:
                expr = f"({perm_expr})" if perm_expr else None
                reqs = create_hybrid_search_request(
                    dense_vector=dense_vectors[i],
                    sparse_vector=sparse_vectors[i],
                    expr=expr,
                    limit=5,
                )
                search_result = hybrid_search(
                    collection_name=milvus_config.item_name_collection,
                    reqs=reqs,
                    ranker_weights=(0.8, 0.2),
                    norm_score=True,
                    output_fields=["item_name", "doc_id"],
                )
                hits = search_result[0] if search_result else []
                matches = [
                    {"item_name": hit.get("entity", {}).get("item_name"),
                     "doc_id": hit.get("entity", {}).get("doc_id"),
                     "score": hit.get("distance")}
                    for hit in hits
                ]
                results.append({"extracted_name": item_name, "matches": matches})
            except Exception as e:  # noqa: BLE001
                logger.warning("主体名检索失败 %s：%s", item_name, e)
                results.append({"extracted_name": item_name, "matches": []})
        return results

    def _step6_align_item_names(self, query_results) -> Dict:
        """评分对齐（逐实体累积，修复原版覆盖 bug）

        规则：>0.85 确认；否则 0.6~0.85 取 Top3 候选；<0.6 忽略
        """
        confirmed: List[str] = []
        options: List[str] = []

        for res in query_results:
            matches = res.get("matches") or []
            if not matches:
                continue
            high = [m for m in matches if m["score"] > ALIGN_CONFIRM_SCORE]
            mid = sorted(
                [m for m in matches if m["score"] >= ALIGN_OPTION_SCORE],
                key=lambda x: x["score"], reverse=True,
            )
            if high:
                confirmed.extend(m["item_name"] for m in high if m["item_name"])
            elif mid:
                options.extend(m["item_name"] for m in mid[:ALIGN_OPTION_TOPN] if m["item_name"])

        return {
            "confirmed_item_names": list(dict.fromkeys(confirmed)),  # 去重保序
            "options": list(dict.fromkeys(options)),
        }

    def _step7_check_confirmation(self, align_result) -> Dict:
        confirmed = align_result.get("confirmed_item_names") or []
        options = align_result.get("options") or []

        # 分支A：有确认主体 → 继续检索
        if confirmed:
            return {"item_names": confirmed, "answer": ""}

        # 分支B：有候选主体 → 反问澄清（不检索）
        if options:
            option_str = "、".join(options)
            return {"item_names": [], "answer": f"您是想咨询以下哪个主体：{option_str}？请明确一下名称。"}

        # 分支C：无匹配 → 不带实体约束继续检索（企业知识库不拒绝）
        return {"item_names": [], "answer": ""}

    def _step8_probe_blocked_alignment(self, item_names) -> List[str]:
        """权限拦截探测：无权限过滤重新对齐

        带权限的对齐未确认时调用。可见主体的强匹配本应在前面对齐中确认，
        因此此处 >0.85 的强匹配必然来自无权访问的文档。探测失败按无拦截
        处理（降级回反问/继续检索的原链路）。
        """
        try:
            query_results = self._step5_vectorize_and_query(item_names, perm_expr=None)
            blocked, seen = [], set()
            for res in query_results:
                for m in res.get("matches") or []:
                    if m.get("score", 0) > ALIGN_CONFIRM_SCORE:
                        doc_id = m.get("doc_id")
                        if doc_id and doc_id not in seen:
                            seen.add(doc_id)
                            blocked.append(doc_id)
            return blocked
        except Exception as e:  # noqa: BLE001
            logger.warning("权限拦截对齐探测失败（按无拦截处理）：%s", e)
            return []
