# -*- coding: utf-8 -*-
from typing import TypedDict


class ImportGraphState(TypedDict):
    """导入图状态 — 在引擎原版基础上增加 kb-platform 权限/任务字段"""
    task_id: str  # 任务唯一ID，用于追踪日志

    # 流程控制标记
    is_md_read_enabled: bool    # 是否启用 Markdown 读取路径
    is_pdf_read_enabled: bool   # 是否启用 PDF 读取路径

    # 路径相关
    local_dir: str       # 当前工作目录或输出目录
    local_file_path: str # 原始输入文件路径
    file_title: str      # 文件标题（文件名去后缀）
    pdf_path: str        # PDF 文件路径 (如果输入是PDF)
    md_path: str         # Markdown 文件路径 (转换后或直接输入的)
    pdf_parse_mode: str  # mineru（外部API） / local（pypdf 本地降级）

    # 内容数据
    md_content: str   # Markdown 的全文内容
    chunks: list      # 切片列表
    item_name: str    # 识别的文档主体名称（产品型号/制度名称/项目代号等，原 item_name 泛化）

    # ===== kb-platform 扩展字段 =====
    doc_id: str            # 平台文档ID（DOC-UP-XXXX，权限/删除的关联键）
    file_hash: str         # SHA256 内容指纹（幂等去重依据）
    permissions: list      # 四维权限配置 [{"scope_type","scope_value"}]
    unit_id: int           # DB knowledge_units.id（导入完成后回填）
    progress_cb: object    # task_manager 进度回调（仅进程内传递，不序列化）

    # 数据库关联
    embeddings_content: list  # 包含向量数据的列表，准备写入 Milvus
