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
- `storage.py`
  - 使用独立 SQLite 保存周度价格、月度母猪数据和已处理来源。
  - 提供原子写入、修订判断和纯本地 known-state 读取。
- `coordinator.py`
  - 将本地 processed URL 记忆接入 MOA 周度日常增量流程。
  - 保持获取层和存储层职责分离，不增加 Step 1B 请求预算。
- `snapshot.py`
  - 从本地 SQLite 生成纯文本 V2 Data Snapshot v0。
  - 只展示已有数据，不进行周期判断或投资建议。
- `trend.py`
  - 位于事实层与未来周期判断层之间，使用纯函数把领域记录转换为透明、可复用的机械趋势特征。
  - 不访问 SQLite、HTTP 或 LLM；结果使用 frozen `NumericTrendFeatures`。
  - 当前支持 MOA 的仔猪、生猪、玉米和派生猪粮比，以及按单一 `SowSourceType` 隔离的能繁母猪存栏。

对应离线测试位于：

- `tests/test_moa_weekly.py`：26 个测试函数。
- `tests/test_sow_monthly.py`：15 个测试函数。
- `tests/test_sow_official.py`：17 个测试函数。
- `tests/test_sow_discovery.py`：13 个测试函数。

当前四组猪周期离线测试合计 71 个测试函数；参数化测试在 pytest 中可能展开为更多测试 case。

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
| `0361804` | 新增猪周期 SQLite schema |
| `6309f6d` | 持久化 MOA 周度记录 |
| `19d0a8a` | 持久化能繁母猪月度记录 |
| `801c773` | 新增本地 known-state 读取 |
| `3690541` | 新增有状态 MOA 周度增量协调器 |
| `0cf912e` | 新增 V2 Data Snapshot v0 |

真实官网 smoke test 已覆盖 MOA 周报、MOA 母猪数据和 NBS 季度母猪数据的关键文本语义。

## 4. 当前阶段

当前位于 **V2.0 数据基础设施向分析方法论过渡阶段**。

已经具备：

- 官方原始文本和文件的解码/解析。
- 严格的数据日期与发布日期语义。
- 官方域名白名单和全国口径过滤。
- 有硬上限的单 URL、受控发现、历史回填和日常增量请求模式。
- 对真实 HTML 文本节点空白、NBSP、UTF-8、NBS 全国上下文和季度末日期的兼容。
- 独立 SQLite schema，以及 MOA 周度和能繁母猪月度记录的原子持久化。
- `processed_sources`、known-state 读取和有状态 MOA 周度日常增量闭环。
- V2 Data Snapshot v0，可纯本地展示数据库概况和当前有效数据。
- 已建立正式长期数据库 `data/pig_cycle.sqlite3`，并成功写入、展示首条真实 MOA 周度数据。
- 已建立正式 Trend Feature Layer：`Fact Layer → Trend Feature Layer → future Cycle Layer`。当前可计算最新/前值、相邻及累计变化、末端连续方向、真实观测间隔和 irregular 标记，但不输出周期阶段、置信度或投资判断。
- 当前历史深度已完成一次工程审计：MOA 为 12 条连续周度观测（2026-05-21 至 2026-08-06，全部相邻 7 天），NBS 为 8 个季度末锚点（2024-09 至 2026-06，全部相邻 3 个月）。这些数据足以验证存储和机械趋势链路，但不足以直接宣布周期规律或投资结论。

尚未完成：

- 周度价格与月度产能的统一时间序列和数据质量状态。
- append-only revision history、完整 point-in-time reader，以及 official-availability / system-knowledge 两种 as-of 语义。
- 猪周期阶段模型、V2A 评分或投资信号。
- 与 V1 主 CLI、Web、报告、邮件或 daily pipeline 的集成。

Step 1C 的第一阶段已经完成。下一个合理方向是建设统一时间序列、数据质量检查和可历史校准的分析方法，同时继续保持 V2 与 V1 解耦；在分析语义稳定后，再让产业数据与 V1 股票 / ETF 能力汇合。

### Step 1C 为什么出现

Step 1C 不只是“增加一个本地数据库”，而是 Step 1B 安全理念的直接延续。

Step 1B 已解决“如何安全、克制地获取官方数据”，但如果程序不长期保存已经访问过的 URL、已经拥有的数据日期和成功解析的记录，下一次运行仍可能忘记以前做过什么，从而重复发现、重复请求官方页面。

可以简化为：

- **Step 1B：学会克制地获取数据。**
- **Step 1C：学会记住已经获取过什么。**

Step 1C 计划包含：

- 本地持久化 `MoaWeeklyRecord`。
- 本地持久化 `SowMonthlyRecord`。
- 按 `source_url + collection_date/month` 等稳定键去重。
- 自动恢复 `known_urls` 和 `known_dates`。
- 已有数据尽量使用纯离线查询。
- 检测缺失周次和缺失月份。
- 保存来源 URL、发布日期等可追溯信息。
- 使用原子写入；数据损坏时明确报错，不静默覆盖或丢弃。
- 由统一协调层管理 bootstrap/history 与 incremental 更新。

`known_urls` / `known_dates` 不只是调用便利参数，而是网络安全机制：它们让程序在发起请求前就知道“这个 URL 已访问过”“这个日期的数据已拥有”，从而跳过不必要的官方网络请求。因此，Step 1C 是“有状态、有记忆的安全数据获取”，不是与 Step 1B 无关的独立存储功能。

### Current effective storage 与 Planned revision history

**Current：** 当前 `moa_weekly_records` 以 `collection_date` 为业务唯一键，`sow_monthly_records` 以 `(month, source_type)` 为业务唯一键，只保存当前 effective payload，继续服务 current Snapshot、current Trend 和日常流程。发生 `updated` 时旧 payload 会被覆盖；`conflict`、`older_ignored` 和 `order_unknown` 的完整 payload 目前也不会长期保存。`processed_sources` 只负责成功处理 URL 的永久记忆、请求前去重和基本来源映射，不是 revision history。

当前 Trend 的 `as_of` 只对调用方传入的 current records 按 `publish_date` 过滤。它能阻止 `publish_date > cutoff` 的当前可见记录进入计算，但不能恢复被覆盖的旧版本、重建历史时点的 effective state，或判断系统当时是否已经抓到该版本。因此，当前 `as_of` 不是完整 point-in-time database。

**Planned / Next architecture：** 保留上述 current effective tables，未来独立增加 append-only 的 MOA weekly 与 sow monthly revision history。每个成功解析的明确官方版本计划保存业务键、完整 payload、`source_url`、`publish_date`、首次成功观察时间 `observed_at`、稳定 `payload_fingerprint`、当次 save decision/status 和 provenance（如 `normal_ingest`、`baseline_import`）。旧 revision 不因后续更新而覆盖。概念上的内部标识为 `revision_id`，版本幂等方向为 `UNIQUE(source_url, payload_fingerprint)`；fingerprint 的精确规范化规则将在 schema 实现前另行确定。

revision 表示一个具体官方 payload/version；save status 表示该版本首次被系统观察时相对于当时 current state 的处理结果。v0 不建设通用 event-sourcing。未来 system-knowledge 查询需要依据 revision append order、`observed_at`、稳定 revision id 和保存判定，按历史观察顺序确定当时状态，而不能只筛选时间后随意取最新版。

Point-in-time 必须区分三类时间：

- business time：Weekly 的 `collection_date`、Sow 的 `month`；
- official time：官方 `publish_date`，表示理论公开时间；
- system knowledge time：`observed_at`，表示系统首次成功获取并解析该版本的时间。

未来 reader 必须分别支持 official-availability as-of 与 system-knowledge as-of。历史页面可能早已发布但直到多年后才由系统回填，两种语义不能混用；不得用 `publish_date` 冒充 `observed_at`，也不得用迁移时间冒充 `publish_date`。

`older_ignored`、`conflict`、`order_unknown` 和来自新 URL 的 `unchanged` 版本未来都应保留完整 revision，但不得因此静默改变 current effective row。conflict 不得在历史查询中任意选择；发布日期缺失时也不得使用本地处理时间猜测官方先后。

当前还有一个明确 detection boundary：`processed_sources` 会永久跳过已成功处理的 URL，所以官方若原地修改同一 URL，系统不会自动发现。未来可评估人工或低频、受控的 revalidation 与 payload fingerprint，但不得以高频轮询、无限重试或大规模重复抓取解决。

现有 MOA 12 条和 NBS 8 条 current rows 未来可作为 baseline revisions 导入，并标注 `baseline_import`。`observed_at` 只能使用能够严格对应当前 source version 的可靠 `processed_at` 证据；无法证明时使用 migration/import time，绝不能伪造为官方发布日期。当前无法恢复此前未保存的被覆盖或忽略 payload，这一历史缺口必须保留说明。

推荐的长期链路是：`revision storage → point-in-time reader → domain records → Trend pure functions`。Storage 负责截止 cutoff 哪个版本可见；Trend 继续只做机械计算，不查询 SQLite、不理解 `processed_sources`，也不处理 revision conflict。append-only revision persistence、两类时间语义、point-in-time reader、冲突处理、baseline provenance 和 look-ahead 回归测试完成前，不进入正式 historical calibration、lead-lag、阈值研究或 backtest；Cycle Layer 继续暂停。

### V2 阶段关系与最终目标

当前与后续阶段关系如下：

```text
Step 1A：核心猪周期指标与基础数据模型
  ↓
Step 1B：安全、低频、官方优先的数据获取层
  ↓
Step 1C：有状态的本地数据仓库与增量更新协调
  ↓
统一猪周期时间序列与数据质量检查
  ↓
核心指标与周期阶段模型
  ↓
与 V1 股票 / ETF 市场数据汇合
  ↓
V2 投资观察、风险提示与初步投资辅助建议
```

V2 的最终目标不是单纯建立猪价或养殖行业数据库。项目仍然是个人猪周期投资观察系统，当前数据基础设施只是为后续投资分析建立可靠地基。

长期数据链路是：

```text
官方猪周期产业数据
（能繁母猪、生猪、仔猪、玉米、豆粕、饲料、猪粮比等）
  ↓
统一时间序列与数据质量检查
  ↓
猪周期核心指标
  ↓
周期阶段判断
  ↓
与 V1 股票 / ETF 市场数据结合
  ↓
牧原股份、温氏股份、新希望、神农集团、养殖 ETF 等标的观察
  ↓
形成阶段性投资观察、风险提示和初步投资辅助建议
```

Step 1C 暂不实现周期评分或投资建议，是因为当前阶段需要先保证数据可靠、可追溯、可复用。这不表示 V2 已转变为纯行业数据库项目。后续仍需让产业数据与 V1 股票/ETF 分析系统汇合，但未来规划不得描述为当前已完成能力。

### 长期分析原则

V2 不是单纯的数据采集器、数据库或猪价仪表盘。其长期目标保持稳定：从官方产业事实出发，形成趋势分析和猪周期状态判断，进一步连接公司盈利能力、市场预期与股价定价，最终回到投资机会观察、风险提示和初步辅助建议，并重新连接 V1 的股票 / ETF 分析能力。

具体分析方法必须允许迭代。阶段划分、时间窗口、指标权重和阈值都属于需要通过历史数据校准的候选方法；当前六阶段框架不是不可修改的金融定律。架构应保证模型被合并、拆分、重定义或概率化时，不需要重建底层采集、来源追溯和 SQLite 存储体系。

分析遵循多指标、多时间尺度原则：单个时点或单个指标不能直接形成周期或投资判断，更重要的是一段时间内的方向、持续性、速度和拐点。周度和月度指标应尊重各自天然频率，不为统一时间轴制造虚假精度；不同指标之间的矛盾不应被强行抹平，因为矛盾本身可能包含领先、滞后或结构变化的信息。

当前 Trend Layer 已正式落地的特征包括：`observation_count`、latest/previous、latest change/pct、window start、cumulative change/pct、末端连续上涨/下降变化次数、`latest_streak_direction`、observation keys、真实 interval units、interval unit 和 irregular interval flag。streak count 表示从序列末端向前连续同方向的**相邻变化次数**，不是记录条数、周数或月数。

Snapshot 与 Trend 的方向语义必须保持区分：Snapshot 的“所示记录方向”描述整个展示窗口内全部相邻变化的符号形态；Trend 的 terminal streak 只描述序列末端向前的连续相邻变化。因此，同一序列可以同时表现为 Snapshot 的“混合”和 Trend 的末端连续下降，两者不冲突，不能直接用 terminal streak 替换 Snapshot 的 whole-window direction helper。

产业周期、公司盈利和市场定价必须分层：行业改善不等于所有猪企同样受益；公司层还需考虑销售价格、完全成本、出栏量、养殖效率和业务结构。行业玉米、豆粕和饲料价格可以描述行业盈利环境，必要时可作为低置信度代理，但不能冒充公司的真实完全成本。股票价格还可能领先产业基本面，因此最终必须判断市场已提前交易了多少。

重要的长期方向和关键模型决策必须同步写入仓库 Markdown，而不能只存在于聊天记录。分析框架发生实质变化时，应更新对应专题文档，并保留改变内容及原因。当前可迭代方法见 `docs/ANALYSIS_FRAMEWORK.md`，关键决策及其理由见 `docs/DECISIONS.md`。

## 5. 关键设计决定

### 数据语义

- 数据所属日期、发布日期和运行/观测日期必须分离。
- MOA 周报的 `collection_date` 严格来自正文采集日，不使用发布日或运行日猜测。
- 母猪 `month` 表示数据所属月，不是网页发布月。
- 核心字段缺失时明确报错，不填 `0`。

### 官方数据来源

数据获取优先级为：

1. 官方直接提供的 CSV / Excel / PDF 等数据文件。
2. 有正式入口、正式文档且适合使用的官方公开 API。
3. 已知且明确的官方 HTML / 数据 URL。
4. 只有在数据缺失且确有必要时，才进行有限、受控的官方页面发现。

项目不是单纯追求 API 优先，而是优先选择官方、公开、稳定、可追溯、请求成本最低的数据入口。不要进行隐藏 API 探测、全站扫描、限制绕过或高频请求。

### Step 1B 的策略调整与受控自动化

V2 早期获取农业农村部等政府官方网站数据时，曾尝试较广泛地读取官方列表页和历史页面，有时需要翻较多页面才能寻找历史数据。出于安全、稳定和对官方服务器友好的考虑，项目随后主动收紧数据获取策略。

当前核心原则是：

> **可靠性、可追溯性、低请求量 > 自动发现能力。**

项目应避免：

- 全站扫描和大量自动翻页。
- 高频或并发抓取。
- 无限重试、因自动重试导致请求量快速放大，或任何限制绕过行为。
- 每次运行重新扫描历史页面。
- 对已经获取过的数据重复请求。

项目也不完全拒绝自动发现。若所有 URL 都必须人工输入，系统会失去必要的自动化价值。因此 Step 1B 最终选择“受控自动化”：

- 已知数据直接使用。
- 已经获取过的数据不重复获取。
- 只有数据缺失时才进行有限发现。
- 历史回填可以使用稍多请求，但必须有不可突破的硬上限。
- 日常增量保持极低请求量。
- 发生拒绝访问、验证码、登录、反爬或请求预算达到上限时立即停止并明确报错，不持续重试。

这一理念已经体现在当前代码中：

- `sow_official.py`
  - 使用官方域名白名单。
  - 针对调用者给定的单一官方 URL 读取 HTML / CSV / Excel / PDF。
  - 不承担全站发现职责。
- `sow_discovery.py`
  - 只读取一个调用者提供的列表入口。
  - 单次最多 5 次请求、最多检查 2 篇候选。
  - 不自动翻页、不并发、不无限重试。
- `moa_weekly.py`
  - 明确区分 bootstrap/history 与 incremental。
  - 历史回填有列表页、文章数和总 GET 数硬上限。
  - 日常增量最多 2 次 GET，且支持通过 `known_urls` / `known_dates` 跳过已知数据。

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

## 7. 历史上下文锚点

最近一次重要上下文刷新基线（2026-08-12）：

- `0cf912e feat: add pig cycle data snapshot`

该 commit 仅用于标记本文档最近一次系统性核对项目状态时的历史上下文，不代表未来的当前 HEAD。实时分支、提交和工作区状态必须以实际执行的 `git status`、`git log` 等命令为准。

### Trend Layer 真实数据验证锚点（2026-08-14）

`04fd9e3 feat: add pig cycle trend features` 已通过 256 项测试和正式 SQLite 数据 smoke test。以下数值仅记录该时点的真实验证结果，不代表未来数据库中的永久业务值：

- MOA 仔猪（6 条）：latest `22.42`，latest change 约 `-0.58`（`-2.52%`），cumulative change 约 `+0.78`（`+3.60%`），terminal down count `2`。
- MOA 生猪：latest `11.13`，latest change 约 `-0.09`（`-0.80%`），cumulative change 约 `+0.65`（`+6.20%`），terminal down count `3`。
- MOA 派生猪粮比：latest 约 `4.506`，latest change 约 `-0.0364`，cumulative change pct 约 `+6.63%`，terminal down count `3`。
- MOA 实际间隔为 `7/7/7/7/7` 天，irregular 为 `false`。
- NBS 母猪 `3961 → 3904 → 3780`：latest change `-124`（约 `-3.18%`），cumulative change `-181`（约 `-4.57%`），terminal down count `2`；间隔为 `3/3` 个月，irregular 为 `false`。

这些结果全部是机械趋势特征，不是猪周期阶段、趋势确认、置信度或投资判断。
