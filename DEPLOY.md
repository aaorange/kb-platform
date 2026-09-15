# 2.9 知识库管理平台 · 部署指南（轻量云服务器 / AutoDL 通用）

3 容器架构：frontend(nginx) + backend(FastAPI) + redis。向量检索走 npz 模式，bge-m3 模型从宿主机只读挂载。

**两种平台二选一：**

| | 轻量应用服务器（腾讯云/阿里云） | AutoDL 实例 |
|---|---|---|
| 定位 | 长期挂演示地址（简历放 IP/域名） | 临时开机演示、GPU 加速可选 |
| 对外端口 | 80（独立公网 IP） | 6006（平台映射域名） |
| 部署命令 | `bash deploy.sh` | `bash deploy.sh 6006` |
| 重启自愈 | 自动（systemd + restart 策略） | 需重新执行 deploy.sh |
| 防火墙 | 云控制台放行 80/22 | 无需配置 |

## 一、服务器准备（二选一）

**A. 轻量应用服务器（推荐长期使用）**
1. 购买：腾讯云/阿里云 轻量应用服务器，**4C8G**，系统镜像 **Ubuntu 22.04**
2. 防火墙：控制台放行 **80、22** 端口
3. SSH 登录后按下面流程操作即可（Docker 由脚本安装，有 systemd 开机自启）

**B. AutoDL 实例**
1. 租用任意 **4 核 8G 内存以上** 机型（无卡模式跑 CPU 推理即可，bge-m3 占内存约 4G）
2. 镜像选 PyTorch / 基础镜像（Ubuntu）均可
3. 开通公网访问：控制台 → 你的实例 → **更多 → 自定义服务** → 开启 **6006 端口**

## 二、本地打包上传（Windows PowerShell，在 d:\Trae_work_proj 下执行）

```powershell
tar --exclude=node_modules --exclude=dist --exclude=.venv --exclude=__pycache__ --exclude=models -czf kb.tar.gz kb-platform
```

上传到 AutoDL（任选其一）：
- 控制台给出的 `scp` 命令（本地 PowerShell 直接执行，端口按控制台提示）
- 或 AutoDL「JupyterLab」网页里直接上传 kb.tar.gz

服务器上解压：
```bash
# 轻量云服务器：
tar xzf kb.tar.gz -C /opt && cd /opt/kb-platform
# AutoDL（数据盘）：
tar xzf kb.tar.gz -C /root/autodl-tmp && cd /root/autodl-tmp/kb-platform
```

## 三、部署（3 步）

```bash
# 1. 修复 Windows 换行符（保险起见执行一次）
sed -i 's/\r$//' deploy.sh

# 2. 填配置：SECRET_KEY 和 LLM_API_KEY
openssl rand -hex 32          # 生成随机串，替换 .env.production 里的 CHANGE_ME
vi backend/.env.production    # LLM_API_KEY=sk-你的DeepSeek密钥

# 3. 一键部署
bash deploy.sh                 # 轻量云服务器（80 端口）
bash deploy.sh 6006            # AutoDL（6006 端口）
```

脚本自动完成：装 Docker（AutoDL 无 systemd 时手动拉起 dockerd）→ 校验数据 → 下载 bge-m3（仅首次，约 2.2GB）→ 构建镜像 → 启动 → 等模型预热 → 初始化种子数据。

## 四、上线验证清单

| # | 验证项 | 操作 | 预期 |
|---|--------|------|------|
| 1 | 容器状态 | `docker compose ps` | 3 个容器全部 Up |
| 2 | 健康检查 | `curl http://localhost/api/health` | `model_ready: true` |
| 3 | 前端可达 | 轻量云：`http://公网IP`；AutoDL：`https://<实例ID>-6006.autodl.pro` | 登录页正常，admin/admin123 登录 |
| 4 | SSE 流式 | 问答页提问 | 回答**逐字**出现；若整段一次性出，检查 nginx.conf 的 `proxy_buffering off` |
| 5 | FAQ 缓存 | 同一问题问第二次 | 秒回（Redis 生效） |
| 6 | 权限拦截 | zhangwei 登录问"高管薪酬" | 拒答 + 权限提示条 |
| 7 | 上传闭环 | 知识维护上传 md → 提问 | 命中新文档 |

## 五、常用运维命令

```bash
docker compose logs -f backend      # 看后端日志（含 LLM/检索报错）
docker compose restart backend      # 重启后端（模型后台预热，服务立即可用）
docker compose down                 # 停止（数据保留在 data/ 目录）
bash deploy.sh                      # 重新部署（会重建种子数据，注意）
docker compose exec backend python scripts/seed.py   # 单独重置种子数据
```

## 六、注意事项

1. **重启实例后**：AutoDL 实例关机再开机后需重新执行 `bash deploy.sh`（dockerd 不会自启，脚本检测到 Docker 未运行会自动拉起，模型和数据都在不会重复下载）
2. **seed.py 是全量重置**（drop_all + create_all）：会清掉问答记录等运行数据，知识文档会重新导入
3. **数据备份**：只需备份 `data/` 目录（kb.db + uploads；向量数据在 Milvus 卷中）
4. **无卡模式**：`~0.1-0.35 元/小时`，演示前开机即可；CPU 推理首问约 7 秒，追问秒级
5. **二期迁移**：换轻量云服务器时，只需把 `docker-compose.yml` 的 `"6006:80"` 改回 `"80:80"`，其余零改动；启用 Milvus 时在 compose 增加 milvus 生态容器并设置 `MILVUS_URI`
