<div align="center">

# 🐷 猪周期观察

[![GitHub stars](https://img.shields.io/github/stars/IntoWildLab/pig-cycle-observer?style=social)](https://github.com/IntoWildLab/pig-cycle-observer/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)

> 面向个人学习的猪周期标的分析与报告推送项目。

[**项目说明**](#项目来源) · [**观察标的**](#当前观察标的) · [**快速开始**](#-快速开始) · [**安全说明**](#安全说明)

</div>

## 项目来源

本项目基于 [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) 进行个人化配置与功能调整。原项目采用 MIT License；本仓库保留原作者版权声明及 [LICENSE](LICENSE) 文件。

本仓库是个人维护的衍生版本，与上游作者不存在官方合作、授权背书或隶属关系。上游项目的问题与本仓库的问题请分别在各自仓库反馈。

## 本版本用途

本版本用于个人“猪周期观察”学习项目，主要用于整理公开行情、新闻和模型分析结果。所有内容仅供信息整理和技术学习，不构成任何投资建议。

### 当前观察标的

| 股票代码 | 名称 |
| --- | --- |
| `002714` | 牧原股份 |
| `300498` | 温氏股份 |
| `000876` | 新希望 |
| `605296` | 神农集团 |
| `159867` | 鹏华中证畜牧养殖ETF |

### 本版本主要调整

- 接入 DeepSeek，并增加空响应检测和仅针对当前标的的单次重试。
- 使用 Tavily 搜索相关新闻。
- 支持通过 126 邮箱推送分析报告。
- 增加 Windows 正式运行脚本 `scripts/run_daily.ps1`。
- 增加仅用于周末或节假日测试的脚本 `scripts/run_weekend_test.ps1`。
- 为运行脚本增加日志记录、旧日志清理和 Clash 代理就绪等待。
- 支持通过 Windows 任务计划程序调用正式运行脚本；计划任务应只调用 `run_daily.ps1`。

### 正式运行与周末测试

- `run_daily.ps1`：用于正式交易日运行，允许发送邮件，不包含 `--force-run`。
- `run_weekend_test.ps1`：仅用于周末或节假日测试，包含 `--force-run` 和 `--no-notify`，不会发送测试邮件。

### 安全说明

- 真实配置只应写入本地 `.env`，不得提交或上传该文件。
- 公开仓库仅提供使用安全占位符的 `.env.example`。
- GitHub Actions 如需使用密钥，应将密钥保存到 GitHub Secrets，不得写入代码、脚本或仓库配置文件。

## ✨ 功能特性

| 能力 | 覆盖内容 |
|------|------|
| AI 决策报告 | 核心结论、评分、趋势、买卖点位、风险警报、催化因素、操作检查清单 |
| 多市场数据聚合 | 覆盖 A股、港股、美股、日股、韩股、台股和 ETF，支持行情、K 线、技术指标、新闻、公告、基本面与报告辅助数据；不同市场的数据源和能力边界见 [市场支持边界](docs/market-support.md) |
| Web / 桌面工作台 | 手动分析、任务进度、历史报告、完整 Markdown、回测、持仓、配置管理、浅色 / 深色主题 |
| Agent 策略问股 | 多轮追问，支持均线、缠论、波浪、趋势、热点、事件、成长、预期等 15 种内置策略，覆盖 Web/Bot/API |
| 智能导入与补全 | 图片、CSV/Excel、剪贴板导入；股票代码/名称/拼音/别名补全 |
| 自动化与推送 | 已验证 Windows 任务计划程序与 126 邮箱推送；GitHub Actions 云端运行尚未完成最终验证 |

> 功能细节、字段契约、基本面 P0 超时语义、交易纪律、数据源优先级、Web/API 行为请看 [完整配置与部署指南](docs/full-guide.md)。

### 当前验证的主要组件

| 类型 | 当前配置 |
|------|------|
| AI 分析 | DeepSeek（OpenAI 兼容接口） |
| 新闻搜索 | Tavily |
| 行情数据 | 项目内置的免费行情数据源及降级机制 |
| 报告通知 | 126 邮箱 |
| 本地自动化 | Windows PowerShell 脚本与任务计划程序 |

其他模型服务商及高级配置请参考[上游项目文档](https://github.com/ZhuLinsen/daily_stock_analysis)。

## 🚀 快速开始

### 1. 获取代码

```powershell
git clone https://github.com/IntoWildLab/pig-cycle-observer.git
Set-Location pig-cycle-observer
```

### 2. 准备 Python 环境

建议使用 Python 3.11，并为项目创建独立虚拟环境，避免影响系统中的其他 Python 项目。

```powershell
py -3.11 -m venv .venv
& ".\.venv\Scripts\python.exe" --version
```

### 3. 安装依赖

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

### 4. 配置环境变量

将 `.env.example` 复制为 `.env`，然后只在本地填写真实配置。真实密钥不得写入 README、脚本或提交到 Git。

```powershell
Copy-Item .env.example .env
```

当前已验证的主要配置包括：

- DeepSeek：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`GENERATION_BACKEND`
- Tavily：`TAVILY_API_KEYS`
- 126 邮箱：`EMAIL_SENDER`、`EMAIL_PASSWORD`、`EMAIL_RECEIVERS`、`EMAIL_SENDER_NAME`
- 观察标的：`STOCK_LIST`

其他模型服务商及高级配置请参考[上游项目文档](https://github.com/ZhuLinsen/daily_stock_analysis)。

### 5. 本地运行

- `scripts/run_daily.ps1`：正式交易日运行，允许发送邮件，不包含 `--force-run`。
- `scripts/run_weekend_test.ps1`：仅用于周末或节假日测试，包含 `--force-run` 和 `--no-notify`。

在项目根目录按用途选择脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_daily.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_weekend_test.ps1"
```

脚本默认使用项目内的 `.venv\Scripts\python.exe`。如需使用项目外虚拟环境，可在当前 PowerShell 进程中设置 `DAILY_STOCK_PYTHON`。Clash 代理默认地址为 `127.0.0.1:7897`，可按本机代理配置调整脚本中的地址和端口。

### 6. 自动运行状态

- Windows 任务计划程序已在本地完成配置验证，可调用 `scripts/run_daily.ps1`。
- GitHub Actions 云端运行尚未完成最终验证，本仓库目前不将其标记为已部署或可直接使用。

## 📱 推送效果

### 决策仪表盘
```
🎯 2026-02-08 决策仪表盘
共分析3只股票 | 🟢买入:0 🟡观望:2 🔴卖出:1

📊 分析结果摘要
⚪ 中钨高新(000657): 观望 | 评分 65 | 看多
⚪ 永鼎股份(600105): 观望 | 评分 48 | 震荡
🟡 新莱应材(300260): 卖出 | 评分 35 | 看空

⚪ 中钨高新 (000657)
📰 重要信息速览
💭 舆情情绪: 市场关注其AI属性与业绩高增长，情绪偏积极，但需消化短期获利盘和主力流出压力。
📊 业绩预期: 基于舆情信息，公司2025年前三季度业绩同比大幅增长，基本面强劲，为股价提供支撑。

🚨 风险警报:

风险点1：2月5日主力资金大幅净卖出3.63亿元，需警惕短期抛压。
风险点2：筹码集中度高达35.15%，表明筹码分散，拉升阻力可能较大。
风险点3：舆情中提及公司历史违规记录及重组相关风险提示，需保持关注。
✨ 利好催化:

利好1：公司被市场定位为AI服务器HDI核心供应商，受益于AI产业发展。
利好2：2025年前三季度扣非净利润同比暴涨407.52%，业绩表现强劲。
📢 最新动态: 【最新消息】舆情显示公司是AI PCB微钻领域龙头，深度绑定全球头部PCB/载板厂。2月5日主力资金净卖出3.63亿元，需关注后续资金流向。

---
生成时间: 18:00
```

### 大盘复盘
```
🎯 2026-01-10 大盘复盘

📊 主要指数
- 上证指数: 3250.12 (🟢+0.85%)
- 深证成指: 10521.36 (🟢+1.02%)
- 创业板指: 2156.78 (🟢+1.35%)

📈 市场概况
上涨: 3920 | 下跌: 1349 | 涨停: 155 | 跌停: 3

🔥 板块表现
领涨: 互联网服务、文化传媒、小金属
领跌: 保险、航空机场、光伏设备
```

## ⚙️ 配置说明

完整环境变量、模型渠道、通知渠道、数据源优先级、交易纪律、基本面 P0 语义和部署说明请参考 [完整配置指南](docs/full-guide.md)。

## 🖥️ Web 界面

Web 工作台提供配置管理、任务监控、手动分析、历史报告、完整 Markdown 报告、Agent 问股、回测、持仓管理、智能导入和浅色 / 深色主题。启动方式：

```bash
python main.py --webui
python main.py --webui-only
```

访问 `http://127.0.0.1:8000` 即可使用。认证、智能导入、搜索补全、历史报告复制、云服务器访问等细节见 [本地 WebUI 管理界面](docs/full-guide.md#本地-webui-管理界面)。

## 🤖 Agent 策略问股

配置任意可用 AI API Key 后，Web `/chat` 页面即可使用策略问股；如需显式关闭可设置 `AGENT_MODE=false`。

- 支持均线金叉、缠论、波浪理论、多头趋势、热点题材、事件驱动、成长质量、预期重估等内置策略
- 支持实时行情、K 线、技术指标、新闻和风险信息调用
- 支持多轮追问、会话导出、发送到通知渠道和后台执行
- 支持自定义策略文件与多 Agent 编排（实验性）

> Agent 具体参数、`skill` 命名兼容、多 Agent 模式和预算护栏见 [完整指南](docs/full-guide.md#本地-webui-管理界面) 与 [LLM 配置指南](docs/LLM_CONFIG_GUIDE.md)。

## 📄 License

[MIT License](LICENSE) © 2026 ZhuLinsen

本仓库保留上游项目的 MIT License 与原作者版权声明。使用、修改和分发时请遵守 [LICENSE](LICENSE)。

## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。作者不对使用本项目产生的任何损失负责。

---
