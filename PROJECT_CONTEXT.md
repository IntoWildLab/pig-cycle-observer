# Pig Cycle Observer — Project Context

## 1. 项目背景

`pig-cycle-observer`（猪周期观察）是一个面向个人学习和信息整理的猪周期观察项目。项目基于 MIT 许可的 `ZhuLinsen/daily_stock_analysis` 衍生，当前仓库由 IntoWildLab 个人化维护，与上游项目不存在官方合作、授权背书或隶属关系。

项目的核心用途是整理公开行情、新闻、官方猪周期数据和模型分析结果，并生成报告。所有内容仅供信息整理、技术学习和研究，不构成投资建议。

当前观察标的为：

| 代码 | 名称 |
| --- | --- |
| `002714` | 牧原股份 |
| `300498` | 温氏股份 |
| `000876` | 新希望 |
| `605296` | 神农集团 |
| `159867` | 鹏华中证畜牧养殖 ETF |

## 2. 代码结构

项目同时包含稳定的 V1 股票分析系统和正在建设的 V2 猪周期官方数据层。

### V1 主系统

- `main.py`：分析任务主入口。
- `server.py` / `api/`：FastAPI 服务。
- `src/core/`：分析主流程编排。
- `src/services/`：业务服务。
- `src/repositories/`：数据访问。
- `src/reports/`：报告生成。
- `data_provider/`：多行情数据源和 fallback。
- `bot/`：机器人入口。
- `apps/dsa-web/`：Web 工作台。
- `apps/dsa-desktop/`：Electron 桌面端。
- `scripts/run_daily.ps1`：Windows 正式交易日运行脚本，允许通知，不含 `--force-run`。
- `scripts/run_weekend_test.ps1`：周末/节假日测试脚本，使用 `--force-run --no-notify`。

V1 已包含股票行情、技术指标、新闻搜索、LLM 分析、报告、邮件通知、Web/桌面工作台和本地自动化。当前个人化环境主要使用 DeepSeek、Tavily、126 邮箱和 Windows 任务计划程序。

### V2 猪周期数据层

V2 代码独立放在 `src/pig_cycle/`，暂未接入 V1 daily pipeline、邮件或股票买卖信号。

- `moa_weekly.py`
  - 解析农业农村部周度畜产品和饲料价格。
  - 字段包括采集日、发布日、仔猪、生猪、玉米、豆粕、育肥猪饲料价格和派生猪粮比。
  - 区分历史回填和日常增量。
  - 历史回填上限：12 个列表页、60 篇文章、72 次 GET。
  - 日常增量固定最多 2 次 GET：首页列表 + 1 篇未知文章。
- `sow_monthly.py`
  - 定义能繁母猪月度数据模型。
  - 解析存栏、环比、同比、月末、季度末和跨年语义。
  - 2026 年正常保有量常量为 3750 万头。
  - 提供官方产能区间 `red_low / yellow_low / green / yellow_high / red_high`。
- `sow_official.py`
  - 对调用者给定的单一官方 URL 执行白名单校验和保守读取。
  - 支持 HTML、CSV、Excel 和 PDF 文本提取。
  - 只接受全国口径能繁母猪数据。
- `sow_discovery.py`
  - 从调用者给定的单一官方列表入口发现少量候选。
  - 单次最多 5 次请求、2 篇候选。
  - 不自动翻页，不做全站扫描。

对应离线测试位于：

- `tests/test_moa_weekly.py`
- `tests/test_sow_monthly.py`
- `tests/test_sow_official.py`
- `tests/test_sow_discovery.py`

## 3. 已完成的重要工作

### V1 稳定性与本地体验

- 修复 `trading_date` 与 `observation_date` 的日期语义：
  - `trading_date` 只表示真实日线交易日。
  - `observation_date` 表示实时估算的观测/运行日。
  - 周末强制运行时，观测日不会覆盖真实交易日。
  - 邮件运行摘要只显示可靠的交易日。
- Windows PowerShell 脚本使用进程级 UTF-8，避免中文和 emoji 日志触发 GBK `UnicodeEncodeError`。
- 公共 SearXNG 实例自动发现在示例配置中默认关闭。

### V2 官方数据基础

根据最近提交记录：

| 提交 | 内容 |
| --- | --- |
| `ad8cdee` | 新增 MOA 周度猪周期数据 |
| `f7ffead` | 新增能繁母猪月度产能数据模型 |
| `d6bc672` | 新增单一官方 URL 保守读取器 |
| `6dae641` | 新增受控官方文章发现器 |
| `2522a0f` | MOA 周报拆分安全历史回填与日常增量 |

真实官网 smoke test 已覆盖 MOA 周报、MOA 母猪数据和 NBS 季度母猪数据的关键文本语义。

## 4. 当前阶段

当前位于 **V2.0 官方数据基础设施阶段**。

已经具备：

- 官方原始文本和文件的解码/解析。
- 严格的数据日期与发布日期语义。
- 官方域名白名单和全国口径过滤。
- 有硬上限的单 URL、受控发现、历史回填和日常增量请求模式。
- 对真实 HTML 文本节点空白、NBSP、UTF-8、NBS 全国上下文和季度末日期的兼容。

尚未完成：

- 官方数据的统一本地持久化。
- `known_urls` / `known_dates` 的自动恢复和跨运行去重。
- 周度价格与月度产能的统一时间序列和数据质量状态。
- 猪周期阶段模型、V2A 评分或投资信号。
- CLI、Web、报告、邮件或 daily pipeline 集成。

下一个合理阶段是 **V2.0 Step 1C：本地官方数据仓库与增量协调层**。应先实现持久化、去重、来源追溯、原子写入和缺口查询，再开始周期阶段判断或用户界面接入。

## 5. 关键设计决定

### 数据语义

- 数据所属日期、发布日期和运行/观测日期必须分离。
- MOA 周报的 `collection_date` 严格来自正文采集日，不使用发布日或运行日猜测。
- 母猪 `month` 表示数据所属月，不是网页发布月。
- 核心字段缺失时明确报错，不填 `0`。

### 官方数据来源

数据获取优先级为：

1. 官方 Excel / CSV / PDF。
2. 有正式入口/文档的官方公开 API。
3. 官方公开 HTML 页面的低频读取。
4. 不做隐藏 API 探测、全站扫描或限制绕过。

- 调用者必须给定明确的官方 URL 或列表入口。
- 所有候选 URL 在请求前再次验证官方域名。
- 403、429、验证码、登录要求、明显反爬或重定向应立即停止。
- 不自动重试、不并发、不更换 IP、不绕验证码。
- 请求数由代码内的硬预算统一约束，不依赖调用者自律。

### 全国口径与来源类型

- `SowSourceType` 明确区分 `nbs`、`moa_reported` 和 `moa_estimate`。
- 解析器不猜测来源类型，由调用者或经过校验的官方域名决定。
- NBS 的“全国生猪存栏……其中，能繁母猪存栏……”可继承紧邻的全国上下文。
- 省、市、县等地方母猪数据不作为正式全国记录。
- 当前只采集官方报告或 NBS 数值，不在获取层自行构造 `moa_estimate`。

### 政策区间

2026 年能繁母猪正常保有量为 3750 万头左右。政策区间集中定义在模块常量中，不散落在业务逻辑：

- `< 88%`：`red_low`
- `88% ≤ ratio < 92%`：`yellow_low`
- `92% ≤ ratio ≤ 103%`：`green`
- `103% < ratio ≤ 106%`：`yellow_high`
- `> 106%`：`red_high`

这是官方产能调控区间，不是 V2A 猪周期评分，也不直接代表去产能、底部、上行早期或股票买点。

### 安全与配置

- 真实密钥、邮箱授权码和个人配置只能保存在本地 `.env`，不得提交。
- `.env.example` 只保留安全占位符。
- GitHub Actions 密钥只能使用 GitHub Secrets。
- 默认稳定性优先，不把 V2 实验性数据层提前接入 V1 主流程。

## 6. 开发与验证约定

- 建议运行环境：Python 3.11 独立虚拟环境。
- 不需要网络的测试应使用 mocked session / fixture，不访问真实官网。
- 真实官网验证应保持手动、低频、单入口和可控请求数。
- 修改 Python 后优先运行相关离线 pytest、`py_compile` 和 `git diff --check`。
- 未经明确确认不执行 `git commit`、`git tag` 或 `git push`。

## 7. 当前 Git 基线

创建本文档时：

- 分支：`main`
- 远程同步状态：与 `origin/main` 同步
- 最新提交：`2522a0f refactor: add safe incremental MOA weekly fetching`
- 工作区：新建本文档前为干净状态

