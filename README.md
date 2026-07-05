# Ruankao Skills

通用软考系统架构设计师备考 skills。目标是把复习方法开源，而不是开源任何个人资料。

## What Is Included

- `ruankao-init`: 初始化资料目录、检查上传资料、生成项目背景卡模板。
- `ruankao-coach-agent`: 路由软考请求，并编排“批改 -> 记录 -> 补洞 -> 下一步”的闭环。
- `ruankao-wrong-note`: 记录综合题、选择题、案例题错题并维护知识点索引。
- `ruankao-answer-grader`: 按采分点批改案例/简答题。
- `ruankao-case-2sigma-review`: 针对一个案例知识点做 2-Sigma 掌握训练。
- `ruankao-case-sprint-10`: 基于用户上传的案例资料抽题并记录掌握情况。
- `ruankao-case-mock-generator`: 生成案例模拟题和标准答案。
- `ruankao-thesis-2sigma`: 论文母题理解、范文背诵、子题迁移训练。
- `ruankao-thesis-argument-prep`: 把知识点映射到用户自己的项目背景卡。
- `ruankao-thesis-reviewer`: 按论文阅卷口径评分和提建议。

## Install

Copy folders under `skills/` into your Codex skills directory, for example:

```bash
cp -R skills/* ~/.codex/skills/
```

Then start with:

```text
使用 $ruankao-init 初始化我的软考复习工作区。
```

## Material Layout

The skills expect users to upload their own materials:

```text
软考/
├── 资料/
│   ├── 教材/
│   ├── 综合题/
│   ├── 案例题/
│   │   ├── 案例教材.pdf
│   │   └── 案例真题.pdf
│   ├── 论文范文/
│   ├── 论文知识/
│   └── 项目背景/
│       └── 项目背景卡.md
└── 输出/
    ├── 知识点索引.md
    ├── 错题本/
    ├── 案例冲刺/
    ├── 案例2sigma/
    ├── 测试/
    └── 论文素材/
```

No exam materials, personal notes, or project backgrounds are included.

## Recommended Study Route

这套 skills 推荐按“综合知识 -> 案例题 -> 论文 -> 最后冲刺”的顺序使用。每个阶段都只依赖用户自己上传的教材、真题、题库、范文和项目背景卡。

### 0. Initialize

第一次使用先运行 `ruankao-init`，让它创建目录、检查资料完整性，并生成项目背景卡模板。

```text
使用 $ruankao-init 初始化我的软考复习工作区，检查资料是否齐全，并告诉我下一步该做什么。
```

建议先准备这些资料：

- 综合知识教材、选择题题库或历年真题
- 案例教材、案例真题
- 论文教材、论文范文、论文知识点
- 自己的项目背景卡

### 1. Comprehensive Knowledge

第一阶段目标是准备综合知识：看资料、刷选择题、把错题沉淀下来。

推荐流程：

1. 根据教材或题库刷选择题。
2. 做错的题用 `ruankao-wrong-note` 记录题干、选项、正确答案、错误原因和知识点。
3. 后续复习时围绕错题本和知识点索引反复回看。

示例：

```text
使用 $ruankao-wrong-note 记录这道选择题错题，保留完整选项，关联到对应知识点，并补一句我错在哪里。
```

这一阶段不要追求一次记住所有细节，重点是把高频错题和薄弱知识点留痕，给后续复习提供抓手。

### 2. Case Analysis

第二阶段目标是准备案例题：先学会知识点，再用真题或模拟题训练采分点表达。

推荐流程：

1. 学习阶段：用 `ruankao-case-2sigma-review` 指定一个案例知识点做 2-Sigma 掌握训练。
2. 练题阶段：做用户自己上传的案例真题，或用 `ruankao-case-mock-generator` 生成模拟题。
3. 批改阶段：用 `ruankao-answer-grader` 按采分点评分。
4. 复盘阶段：把真正属于知识点缺口的题用 `ruankao-wrong-note` 记录下来。

示例：

```text
使用 $ruankao-case-2sigma-review 训练 CAP 这个案例知识点，一次只问我一个诊断题。
```

```text
使用 $ruankao-case-mock-generator 生成一道关于质量属性的案例模拟题，并附标准答案和采分点。
```

```text
使用 $ruankao-answer-grader 按采分点评分我的答案，并列出哪些内容需要记录到错题本。
```

这一阶段的关键不是“看懂答案”，而是能在空白状态下写出采分点。

### 3. Thesis

第三阶段目标是准备论文：先准备自己的项目背景卡，再围绕论文母题形成可背、可默写、可迁移的范文素材。

推荐流程：

1. 用 `ruankao-init` 生成或检查 `软考/资料/项目背景/项目背景卡.md`。
2. 用 `ruankao-thesis-argument-prep` 把论文知识点映射到自己的项目背景。
3. 用 `ruankao-thesis-2sigma` 训练论文母题、范文骨架、主体段和子题迁移。
4. 闭卷默写一篇完整论文。
5. 用 `ruankao-thesis-reviewer` 按阅卷口径评分，并根据建议重写薄弱段落。

示例：

```text
使用 $ruankao-thesis-argument-prep 把这个论文题目映射到我的项目背景卡，并准备可复用的项目实践素材。
```

```text
使用 $ruankao-thesis-2sigma 帮我背诵并迁移这篇论文范文，一次只问我一个问题。
```

```text
使用 $ruankao-thesis-reviewer 批改我的完整论文，并判断是否能过线。
```

这一阶段要尽早完成项目背景卡，因为论文不是临场编项目，而是把同一个项目迁移到不同论文题材里。

### 4. Final Sprint

最后一到两周进入冲刺阶段，交给 `ruankao-coach-agent` 做整体规划和闭环推进。

推荐流程：

1. 让 coach 根据剩余时间、错题本、案例掌握情况、论文短板，规划最后训练计划。
2. 每天按 coach 给出的最小任务推进：错题复习、案例冲刺、论文默写或整卷批改。
3. 使用 `ruankao-case-sprint-10` 做案例高频知识点抽查。
4. 每轮训练后由 coach 串起“批改 -> 记录 -> 补洞 -> 下一步”。

示例：

```text
使用 $ruankao-coach-agent 根据我的错题本、案例掌握情况和论文练习情况，规划最后两周软考冲刺计划。
```

```text
使用 $ruankao-case-sprint-10 从我上传的资料中抽查 10 个高频案例知识点。
```

冲刺阶段不要再大面积铺新资料，优先处理反复丢分点、案例采分点、论文结构和项目实践表达。

## Privacy Boundary

This package only contains workflows, scoring rubrics, templates, and scripts. Users must upload their own textbooks, past papers, model essays, wrong questions, and project-background card.
