# -*- coding: utf-8 -*-
"""Markdown 图片处理节点 — 多模态图片理解 + MinIO 托管

重写自课程版，修复原 6 处缺陷：
1. from datetime import time 遮蔽 time 模块（限速器直接崩）
2. _upload_images_batch 中 urls=[] 却按下标赋值（TypeError）
3. base64 双重解码（应 encode 而非 decode）
4. 备份新文件时写入的是文件名而非内容
5. 返回 dict 重复 key 'md_content'（后者覆盖前者）
6. _upload_images_batch 缺 return
"""
import base64
import os
import re
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Tuple

from langchain_openai import ChatOpenAI
from minio.deleteobjects import DeleteObject

from app.engine.config.config import lm_config, minio_config
from app.engine.import_process.base import NodeBase
from app.engine.import_process.prompt import IMAGE_SUMMARY
from app.engine.import_process.state import ImportGraphState
from app.engine.tool.logger import logger
from app.engine.utils.minio_utils import get_minio_client

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MD_IMG_PATTERN = r"!\[.*?\]\(.*?"


class NodeMDImg(NodeBase):
    """图片摘要（VL 模型）→ 上传 MinIO → 替换 md 内图片引用"""

    name = "node_md_img"

    def process(self, state: ImportGraphState):
        md_content, md_path_obj, images_dir = self._step1_get_content(state)
        if not images_dir.exists():
            logger.info("图片目录不存在，跳过图片处理：%s", images_dir)
            return {"md_content": md_content}

        images = self._step2_scan_images(md_content, images_dir)
        if not images:
            logger.info("无待处理图片")
            return {"md_content": md_content}

        file_title = md_path_obj.stem
        summaries = self._step3_generate_summaries(file_title, images)
        new_md_content = self._step4_upload_and_replace(file_title, images, summaries, md_content)
        self._step5_backup_new_md_file(state["md_path"], new_md_content)

        return {"md_content": new_md_content}

    # ===== step1: 读取 md 与图片目录 =====
    def _step1_get_content(self, state) -> tuple[str, Path, Path]:
        md_path = state.get("md_path")
        if not md_path:
            raise ValueError("请指定md文件路径")
        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            raise FileNotFoundError(f"指定的md文件不存在：{md_path}")

        # 编码容错：utf-8 优先，GBK 旧文件回退 gb18030，字节级损坏（截断/半字符）ignore 兜底
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
        except UnicodeDecodeError:
            logger.warning("md 文件非 UTF-8 编码，回退 gb18030：%s", md_path)
            with open(md_path, "r", encoding="gb18030", errors="replace") as f:
                md_content = f.read()

        images_dir = md_path_obj.parent / "images"
        return md_content, md_path_obj, images_dir

    # ===== step2: 扫描被 md 引用的图片 =====
    def _step2_scan_images(self, md_content: str, images_dir: Path) -> List[Tuple[str, str, Tuple[str, str] | None]]:
        images = []
        for image_file in os.listdir(images_dir):
            file_ext = Path(image_file).suffix.lower()
            if file_ext not in IMAGE_EXTENSIONS:
                continue
            context = self._find_image_in_md(md_content, image_file)
            if not context:
                logger.warning("图片未被 md 引用，跳过：%s", image_file)
                continue
            image_path = str(images_dir / image_file)
            images.append((image_file, image_path, context))
        logger.info("待处理图片 %d 张", len(images))
        return images

    def _find_image_in_md(self, md_content: str, image_file: str, context_len: int = 100) -> Tuple[str, str] | None:
        pattern = re.compile(MD_IMG_PATTERN + re.escape(image_file) + r"\)")
        match = pattern.search(md_content)
        if not match:
            return None
        start, end = match.span()
        pre_text = md_content[max(0, start - context_len):start]
        post_text = md_content[end:min(end + context_len, len(md_content))]
        return pre_text, post_text

    # ===== step3: VL 模型生成图片摘要（带滑动窗口限速）=====
    def _step3_generate_summaries(self, file_title: str, images) -> Dict[str, str]:
        summaries = {}
        request_deque: Deque[float] = deque()
        for image_file, image_path, context in images:
            self._apply_api_rate_limit(request_deque, max_requests=10)
            summaries[image_file] = self._summarize_image(image_path, file_title, context)
        return summaries

    def _apply_api_rate_limit(self, request_deque: Deque[float], max_requests: int, window_size: int = 60):
        import time
        current_time = time.time()
        while request_deque and current_time - request_deque[0] >= window_size:
            request_deque.popleft()
        if len(request_deque) >= max_requests:
            sleep_duration = window_size - (current_time - request_deque[0])
            if sleep_duration > 0:
                logger.info("VL API 限速，等待 %.1fs", sleep_duration)
                time.sleep(sleep_duration)
                current_time = time.time()
                while request_deque and current_time - request_deque[0] >= window_size:
                    request_deque.popleft()
        request_deque.append(current_time)

    def _summarize_image(self, image_path: str, file_title: str, context) -> str:
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            image_base64 = base64.b64encode(image_data).decode("utf-8")
            prompt = IMAGE_SUMMARY.format(file_title=file_title, context=context)

            chat_model = ChatOpenAI(
                model=lm_config.vl_model,
                api_key=lm_config.vl_api_key,
                base_url=lm_config.vl_base_url,
                temperature=lm_config.llm_temperature,
            )
            message = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                ],
            }]
            response = chat_model.invoke(message)
            return response.content.strip().replace("\n", "")
        except Exception as e:  # noqa: BLE001
            logger.error("图片摘要生成失败 %s：%s", image_path, e)
            return "图片描述"

    # ===== step4: 上传 MinIO 并替换 md 引用 =====
    def _step4_upload_and_replace(self, file_title: str, images, summaries: Dict[str, str], md_content: str) -> str:
        upload_dir = f"{minio_config.img_dir}/{file_title}".replace(" ", "")
        self._clean_minio_directory(upload_dir)
        urls = self._upload_images_batch(upload_dir, images)
        image_info = {f: (summies, urls[f]) for f, summies in summaries.items() if f in urls}
        return self._process_md_file(md_content, image_info)

    def _clean_minio_directory(self, upload_dir: str) -> None:
        try:
            minio_client = get_minio_client()
            objects = minio_client.list_objects(minio_config.bucket_name, upload_dir, recursive=True)
            delete_list = [DeleteObject(obj.object_name) for obj in objects]
            if delete_list:
                errors = minio_client.remove_objects(minio_config.bucket_name, delete_list)
                for error in errors:
                    logger.error("MinIO 删除失败：%s", error)
        except Exception as e:  # noqa: BLE001
            logger.error("MinIO 目录清理失败（不影响主流程）：%s", e)

    def _upload_images_batch(self, upload_dir: str, images) -> Dict[str, str]:
        urls: Dict[str, str] = {}
        for image_file, image_path, _ in images:
            object_name = f"{upload_dir}/{image_file}"
            urls[image_file] = self._upload_to_minio(image_path, object_name)
        return urls

    def _upload_to_minio(self, image_path: str, object_name: str) -> str:
        import mimetypes
        minio_client = get_minio_client()
        # 显式指定 content-type：不传时可能存为 octet-stream，
        # 浏览器地址栏直接打开图片会变成下载
        content_type = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
        minio_client.fput_object(minio_config.bucket_name, object_name, image_path,
                                 content_type=content_type)
        # URL 用公网前缀（浏览器直读）；操作端点是容器内地址，外部不可达。
        # 默认经 nginx 80 端口代理 /kb-img/，无需云安全组放行 9000
        base = (minio_config.public_url
                or f"http://{minio_config.endpoint}/{minio_config.bucket_name}")
        return f"{base}/{object_name}"

    def _process_md_file(self, md_content: str, image_info: Dict[str, Tuple[str, str]]) -> str:
        for image_file, (summary, url) in image_info.items():
            pattern = re.compile(MD_IMG_PATTERN + re.escape(image_file) + r"\)")
            md_content = pattern.sub(lambda _: f"![{summary}]({url})", md_content)
        logger.info("图片引用替换完成")
        return md_content

    # ===== step5: 备份新 md（原文件不动）=====
    def _step5_backup_new_md_file(self, origin_md_path: str, new_md_content: str) -> str:
        new_md_file_name = os.path.splitext(origin_md_path)[0] + "_new.md"
        with open(new_md_file_name, "w", encoding="utf-8") as f:
            f.write(new_md_content)
        return new_md_file_name
