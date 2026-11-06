# 部署手册

> 目标：在一台全新的 Ubuntu 云服务器上，30 分钟内跑出可公网访问的演示地址。
> 赛题要求"评审期间须保持服务可用"，因此部署完成后必须配置开机自启。

## 0. 服务器选型

| 项 | 建议 | 说明 |
|---|---|---|
| 规格 | **2 核 4 G**（4C8G 更稳） | 向量模型 BGE-M3 常驻约 2 GB，解析时峰值再加 1 GB |
| 系统 | Ubuntu 22.04 / 24.04 | 镜像自带 Docker 源 |
| 硬盘 | 40 GB 起 | 模型 2.2 GB + torch 1 GB + 论文数据 |
| 带宽 | 3 Mbps 以上 | PDF 上传与图表下载都会用到 |
| 到期 | **至少覆盖到 2027-01-31** | 评审意见预计 1 月底发布，期间服务不能停 |

> 2C4G 部署后务必加 2 GB swap，否则大论文解析时容易被 OOM Killer 杀掉。

## 1. 系统准备

```bash
# 以 root 登录后
adduser sciloom && usermod -aG sudo sciloom    # 建议不要长期用 root
apt update && apt upgrade -y

# swap（2C4G 必做）
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Docker
curl -fsSL https://get.docker.com | sh
docker compose version
```

国内服务器拉镜像慢，可先配加速器（阿里云容器镜像服务控制台有专属地址）：

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://<你的加速器地址>"] }
EOF
systemctl restart docker
```

## 2. 拉代码与配置

```bash
git clone <你的仓库地址> /opt/sciloom && cd /opt/sciloom
cp .env.example .env
nano .env      # 填 LLM_API_KEY / HF_ENDPOINT / CORS_ORIGINS
```

关键项：

```ini
LLM_API_KEY=sk-...              # DeepSeek
LLM_MODEL=deepseek-chat
EMBEDDING_BACKEND=local
EMBEDDING_MODEL=BAAI/bge-m3
HF_ENDPOINT=https://hf-mirror.com
HF_OFFLINE=false                # 首次启动要下载模型，下载完可改 true
CORS_ORIGINS=http://<服务器公网IP>
```

## 3. 启动

```bash
docker compose build      # 首次 15-25 分钟（torch + 依赖）
docker compose up -d
docker compose ps

# 等到 ready=true 再对外宣布地址，否则评审第一次提问会撞上冷启动
python scripts/wait_ready.py http://<服务器公网IP>
```

首次启动会从 hf-mirror 下载 BGE-M3（约 2.2 GB），视带宽 3-15 分钟。
下载完成后建议把 `.env` 里的 `HF_OFFLINE` 改为 `true` 并重启，避免每次启动探测 Hub 超时。

启动后服务会在后台依次：加载向量模型（15–30 s，2C4G 上更久）→ 补齐所有文档的索引。
`/api/health` 会返回进度：

```json
{"status":"ok","ready":true,
 "warmup":{"embedder":true,"indexed":9,"documents":10,"warming":false}}
```

`indexed` 比 `documents` 少是正常的——超过 200 页的文档（如 541 页教材）只参与阅读演示，
不建向量索引。

## 4. 灌入演示数据

空库打不开任何功能。用脚本把官方测试集与谱系论文灌进去：

```bash
# 在本地或服务器上执行均可，指向线上地址
python scripts/seed_demo.py http://<服务器公网IP>
```

## 5. 评审账号

赛题要求"如需登录，须提供评审专用测试账号"。当前版本不强制登录，
但建议在演示说明里写清楚 **无需登录、直接访问**，并附上预置好的文献库。

若后续加了鉴权，在这里补充账号创建步骤：

```bash
# 示例（当前未启用）
# docker compose exec api python -m app.cli create-reviewer --user reviewer --password xxxx
```

## 6. 开机自启与守护

```bash
# compose 已设置 restart: always，只需确保 Docker 开机自启
systemctl enable docker

# 每日巡检（可选）
cat > /etc/cron.daily/sciloom-health <<'EOF'
#!/bin/sh
curl -fsS http://127.0.0.1/api/health || systemctl restart docker
EOF
chmod +x /etc/cron.daily/sciloom-health
```

## 7. 上线自查清单

- [ ] `curl http://<IP>/api/health` 返回 `{"status":"ok"}`
- [ ] 浏览器打开 `http://<IP>/` 能看到文献台
- [ ] 上传一篇 PDF 能解析出标题与章节树
- [ ] 问一个问题能流式返回并带 `[c1]` 引用（SSE 未被 nginx 缓冲）
- [ ] 引用图谱能渲染出节点
- [ ] 服务器重启后服务自动恢复
- [ ] `.env` 没有进 git（`git status` 应干净）

## 8. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| `502 Bad Gateway` | api 容器未就绪或崩了 | `docker compose logs api`；多半是模型下载失败或 OOM |
| 问答一直转圈不出字 | nginx 缓冲了 SSE | 确认 `location /api/` 里 `proxy_buffering off` |
| 上传 413 | nginx 限制 | `client_max_body_size 200m` |
| 解析极慢 / 被 kill | 内存不足 | 加 swap，或把 `MAX_PAGES_INLINE` 调小 |
| 首次提问等 30 秒 | 向量模型没预热 | 已内置启动预热；检查日志是否出现"向量模型就绪" |
| 中文乱码 | 容器 locale | 镜像已设 `PYTHONUNBUFFERED`，若仍有问题在 compose 加 `LANG=C.UTF-8` |

## 9. 回滚

```bash
docker compose down
git checkout <上一个可用 commit>
docker compose up -d --build
```
