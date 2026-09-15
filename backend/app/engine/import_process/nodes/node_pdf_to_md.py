# -*- coding: utf-8 -*-
"""PDF 转 Markdown 节点 — 双模式

mineru（默认）：上传 MinerU API 解析（扫描件/图文混排 PDF，产出带图片的 md）
local       ：pypdf 本地提取（纯文本 PDF，无图片、零成本、零外部依赖）

模式由 task_manager 预判后写入 state['pdf_parse_mode']。
"""
import shutil
import time
from pathlib import Path
from zipfile import ZipFile

import requests

from app.engine.config.config import mineru_config
from app.engine.import_process.base import NodeBase
from app.engine.import_process.state import ImportGraphState
from app.engine.tool.logger import logger

POLL_TIMEOUT = 600   # MinerU 解析轮询上限（秒）
POLL_INTERVAL = 3


class NodePDFToMD(NodeBase):
    """PDF 结构化解析"""

    name = "node_pdf_to_md"

    def process(self, state: ImportGraphState):
        pdf_path_obj, output_dir_obj = self._step1_validate_paths(state)

        if state.get("pdf_parse_mode") == "local":
            md_path = self._local_parse(pdf_path_obj, output_dir_obj)
        else:
            zip_url = self._step2_upload_and_poll(pdf_path_obj)
            md_path = self._step3_download_and_extract(zip_url, output_dir_obj, pdf_path_obj.stem)

        return {"md_path": md_path}

    # ===== 本地降级：pypdf 提取纯文本 → 简单 md =====
    def _local_parse(self, pdf_path_obj: Path, output_dir_obj: Path) -> str:
        from pypdf import PdfReader

        logger.info("使用本地 pypdf 解析：%s", pdf_path_obj.name)
        reader = PdfReader(str(pdf_path_obj))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(p.strip() for p in pages if p.strip())
        if not text.strip():
            raise ValueError("本地解析结果为空（可能是扫描件），应改用 MinerU 模式重试")

        out_dir = output_dir_obj / pdf_path_obj.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"{pdf_path_obj.stem}.md"
        md_path.write_text(text, encoding="utf-8")
        logger.info("本地解析完成：%d 页 → %s", len(reader.pages), md_path)
        return str(md_path.absolute())

    # ===== MinerU 外部 API =====
    def _step1_validate_paths(self, state: ImportGraphState):
        pdf_path = state.get("pdf_path")
        local_dir = state.get("local_dir")
        if not pdf_path:
            raise ValueError("请指定PDF文件路径")
        if not local_dir:
            raise ValueError("请指定输出目录")

        pdf_path_obj = Path(pdf_path)
        output_dir_obj = Path(local_dir)

        if not pdf_path_obj.exists():
            raise FileNotFoundError(f"指定的PDF文件不存在：{pdf_path}")
        if not output_dir_obj.exists():
            output_dir_obj.mkdir(parents=True, exist_ok=True)
        return pdf_path_obj, output_dir_obj

    def _step2_upload_and_poll(self, pdf_path_obj: Path) -> str:
        """上传 pdf 到 MinerU 并轮询解析结果"""
        if not mineru_config.api_token:
            raise ValueError("MINERU_API_TOKEN 未配置：无法使用 MinerU 解析，请检查 pdf_parse_mode 预判")

        token = mineru_config.api_token
        url = f"{mineru_config.base_url}/file-urls/batch"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        data = {"files": [{"name": pdf_path_obj.name}], "model_version": "vlm"}

        response = requests.post(url, headers=header, json=data, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"申请文件上传连接失败：{response.text}，状态码：{response.status_code}")
        result = response.json()
        if result["code"] != 0:
            raise RuntimeError(f"申请文件上传连接失败，原因：{result['msg']}")

        batch_id = result["data"]["batch_id"]
        signed_url = result["data"]["file_urls"][0]
        logger.info("MinerU batch_id=%s", batch_id)

        # 上传文件
        with open(pdf_path_obj, "rb") as f:
            res_upload = requests.put(signed_url, data=f, timeout=300)
        if res_upload.status_code != 200:
            raise RuntimeError(f"上传文件失败：状态码：{res_upload.status_code}")

        # 轮询结果
        poll_url = f"{mineru_config.base_url}/extract-results/batch/{batch_id}"
        start_time = time.time()
        logger.info("【开始轮询】最大超时 %ds，batch_id=%s", POLL_TIMEOUT, batch_id)

        while True:
            elapsed = time.time() - start_time
            if elapsed > POLL_TIMEOUT:
                raise RuntimeError(f"MinerU 解析超时（>{POLL_TIMEOUT}s），batch_id={batch_id}")

            try:
                res = requests.get(poll_url, headers=header, timeout=10)
            except Exception as e:  # noqa: BLE001
                logger.warning("轮询网络异常：%s，%ds 后重试", e, POLL_INTERVAL)
                time.sleep(POLL_INTERVAL)
                continue

            if res.status_code != 200:
                raise RuntimeError(f"获取任务结果失败，状态码：{res.status_code}")

            poll_data = res.json()
            if poll_data["code"] != 0:
                raise RuntimeError(f"获取任务结果失败：{poll_data['msg']}")

            result_item = poll_data["data"]["extract_result"][0]
            state_ = result_item["state"]

            if state_ == "done":
                logger.info("MinerU 解析完成，耗时 %.1fs", elapsed)
                return result_item["full_zip_url"]
            if state_ == "failed":
                raise RuntimeError(f"MinerU 任务失败：{result_item.get('err_msg', '未知错误')}")

            logger.info("MinerU 处理中，已耗时 %.0fs", elapsed)
            time.sleep(POLL_INTERVAL)

    def _step3_download_and_extract(self, zip_url, output_dir_obj: Path, file_title: str) -> str:
        response = requests.get(zip_url, timeout=300)
        if response.status_code != 200:
            raise RuntimeError(f"ZIP 下载失败，状态码：{response.status_code}")

        zip_save_path = output_dir_obj / f"{file_title}.zip"
        with open(zip_save_path, "wb") as f:
            f.write(response.content)

        unzip_dir_obj = output_dir_obj / file_title
        if unzip_dir_obj.exists():
            shutil.rmtree(unzip_dir_obj)
        unzip_dir_obj.mkdir(parents=True, exist_ok=True)

        with ZipFile(zip_save_path, "r") as zip_file:
            zip_file.extractall(unzip_dir_obj)

        md_file_obj = unzip_dir_obj / "full.md"
        if not md_file_obj.exists():
            raise FileNotFoundError(f"MinerU 结果包中未找到 full.md：{unzip_dir_obj}")
        new_md_path = md_file_obj.with_name(file_title + ".md")
        md_file_obj.rename(new_md_path)
        logger.info("MinerU 结果已解压：%s", new_md_path)
        return str(new_md_path.absolute())
