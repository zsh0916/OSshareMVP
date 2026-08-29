# Smart Office AI Platform

一个可扩展的 FastAPI + Vue 3 智能办公示例项目，包含 OA 申请与审批、知识检索、会议纪要、员工测评、报告生成、飞书消息分流和基于角色的权限控制。
![项目主界面](frontend/images/overview.png)
公开版本中的员工、合作方、会话、群聊和工作流均使用 `USER_*`、`PARTNER_*`、`CHAT_ID_*`、`WORKFLOW_*` 等代号。请勿向仓库提交真实 `.env`、员工 CSV、SQLite 数据库或消息日志。

## 目录

```text
backend/                  Python 后端与飞书 Worker
  web_api.py              FastAPI 应用主入口
  feishu_worker.py        飞书事件消费入口
  auth_system.py          身份、权限、通知和审批 API
  db.py                   数据表、仓储函数与统一连接扩展点
  dify_client.py          AI 服务提供方适配层
frontend/                 Vue 3 前端
scripts/                  统一维护命令、环境安装与发布检查
data/                     本地私有数据与公开脱敏样例
tests/                    安全与回归检查
```

根目录 `web_api.py` 和 `main.py` 是兼容入口，旧启动方式仍然有效。

## 本地启动

1. 复制 `.env.example` 为 `.env`，生成强随机 `APP_JWT_SECRET`，并设置管理员密码。
2. 复制 `data/employee_info.example.csv` 为 `data/employee_info.csv`，按私有环境需要替换代号。
3. 安装后端依赖：`python -m pip install -r requirements.txt`。
4. 运行 API：`python -m uvicorn backend.web_api:app --reload --port 8000`。
5. 在 `frontend/` 运行 `npm install` 和 `npm run dev`。

也可继续使用 `start_backend.bat` 与 `start_frontend.bat`。

## 可扩展接口

- AI 提供方：实现或替换 `backend/dify_client.py`，业务路由无需改变。
- 数据层：通过 `backend/db.py` 统一连接策略，可继续抽象 repository 后接入其他数据库。
- 事件来源：参考 `backend/feishu_worker.py` 增加新的事件适配器。
- 前端模块：功能页面采用异步加载，新模块不会自动增大登录首屏包。
- 能力发现：`GET /api/meta/capabilities` 返回公开模块和扩展点，不包含密钥。

现有 `/api/...` 路径保持兼容。新增 API 应优先采用 `/api/v1/<resource>` 命名，并通过独立 `APIRouter` 注册，避免继续扩大主应用文件。

## 发布前安全检查

```powershell
python -m scripts.public_release_check
python -m scripts.manage check-config
python -m compileall -q backend scripts
cd frontend
npm run build
```

其他维护命令：`python -m scripts.manage init-db`、`inspect-oa` 和 `check-ai`。
