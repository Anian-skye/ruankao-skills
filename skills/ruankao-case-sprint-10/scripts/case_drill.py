#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import json
import random
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Any


PDF_RELATIVE_PATH = Path("软考/资料/案例题/案例教材.pdf")
REAL_CASE_PDF_RELATIVE_PATH = Path("软考/资料/案例题/案例真题.pdf")
DATA_DIR = Path("软考/输出/案例冲刺")
BANK_PATH = DATA_DIR / "题库.json"
REAL_CASE_BANK_PATH = DATA_DIR / "真题索引.json"
STATE_PATH = DATA_DIR / "掌握情况.json"
REPORT_PATH = DATA_DIR / "掌握情况.md"
REAL_CASE_SCREENSHOT_DIR = Path.home() / "case-drill-screenshots" / "real-cases"
DEFAULT_PICK_COUNT = 10
DEFAULT_REAL_CASE_COUNT = 2
TOPIC_COOLDOWN_DAYS = 3
CHAPTER_COOLDOWN_DAYS = 1
PROMPT_COOLDOWN_DAYS = 3

WATERMARK_PATTERNS = (
    "芝士架构案例冲刺宝典",
    "微信添加 deckardcain4 进群一起学",
    "凯恩编辑整理",
    "版权",
    "盗版",
    "备案",
    "知识产权",
)

FILTER_KEYWORDS = ("小结", "典型例题", "某", "案例题型", "刷题形式", "前言", "后记", "关注范围", "概念辨析", "典型架构")
REAL_CASE_TOC_SKIP_TITLES = {"目录", "系统架构设计师-按照知识点导出历年真题（案例题)"}
REAL_CASE_TITLE_PATTERN = re.compile(r"[（(](20\d{2})年(\d{1,2})月系统架构真题-第(\d+)题[）)]")
REAL_CASE_PROBLEM_PATTERN = re.compile(r"问题[（(]([一二三四123456789]+)[）)]")
REAL_CASE_SUBJECT_PATTERNS = (
    re.compile(r"阅读以下关于(.+?)的(?:叙述|说明)"),
    re.compile(r"阅读下列关于(.+?)的(?:叙述|说明)"),
    re.compile(r"阅读以下有关(.+?)的(?:叙述|说明)"),
    re.compile(r"请详细阅读以下关于(.+?)的(?:叙述|说明)"),
    re.compile(r"阅读以下关于(.+?)的相关描述"),
    re.compile(r"阅读以下关于(.+?)的描述"),
)


@dataclass
class Topic:
    topic_id: str
    chapter_no: int
    chapter_title: str
    chapter_importance: str
    heading: str
    title: str
    importance: str
    page: int
    end_page: int
    depth: int
    score: int
    question_prompt: str


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_title(raw: str) -> tuple[str, str]:
    text = normalize_spaces(raw)
    match = re.search(r"（([^）]+)）", text)
    importance = match.group(1) if match else ""
    if match:
        text = normalize_spaces(text[: match.start()] + text[match.end() :])
    return text.strip(" ."), importance


def importance_score(text: str) -> int:
    if "超级重点" in text:
        return 6
    if "重点" in text:
        return 4
    if "次重点" in text:
        return 2
    return 1


def should_skip_topic(title: str) -> bool:
    if not title:
        return True
    return any(keyword in title for keyword in FILTER_KEYWORDS)


def exam_parts(*parts: str) -> str:
    return "\n".join(f"（{index}）{part}" for index, part in enumerate(parts, start=1))


def prompt_variants(*variants: tuple[str, ...]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, parts in enumerate(variants, start=1):
        prompt = exam_parts(*parts)
        if prompt in seen:
            continue
        seen.add(prompt)
        payload.append({"prompt_id": f"q{index:02d}", "question_prompt": prompt})
    return payload


SPECIFIC_PROMPT_VARIANTS = {
    "用例图": prompt_variants(
        ("写出用例图的 3 个基本元素", "指出参与者识别时需要满足的关键条件", "按顺序写出用例建模的基本步骤"),
        ("分别说明包含、扩展、泛化 3 种关系的含义", "指出这 3 种关系在图中的判别方法", "给出各自一个典型使用场景"),
        ("指出用例图里系统边界的作用", "说明参与者与用例之间连线表示什么", "说明为什么用例图不直接表达对象内部实现"),
    ),
    "面向对象分析方法": prompt_variants(
        ("指出软考里面向对象分析主要使用的建模工具", "写出高频考查的 UML 图类型", "比较顺序图与通信图的关注重点"),
        ("写出面向对象分析阶段通常要完成的 3 类核心工作", "指出需求分析阶段常用的对象识别来源", "说明为什么分析模型不能直接等同于代码设计"),
        ("分别指出用例图、类图、顺序图在分析阶段回答什么问题", "说明三者之间的信息传递关系", "指出案例题里最容易混淆的一对图"),
    ),
    "识别原则": prompt_variants(
        ("指出类识别常用的方法", "说明实体类、边界类、控制类各自的作用", "写出三类对象常见的识别特征"),
        ("从名词提取法角度说明如何识别候选类", "指出哪些名词通常不应该直接当成类", "给出一个从需求描述中筛选类的例子"),
        ("分别写出实体类、边界类、控制类在案例中的典型语言信号", "说明三类对象之间通常如何协作", "指出控制类最容易被误判成什么"),
    ),
    "设计原则": prompt_variants(
        ("写出面向对象设计的 5 个基本原则", "任选 3 个原则说明其设计意图", "指出这些原则与高内聚低耦合的关系"),
        ("分别写出开闭原则、里氏替换原则、依赖倒置原则各自要求什么", "各给出一个符合该原则的设计做法", "各给出一个违反该原则的设计现象"),
        ("从扩展性角度说明为什么要遵守设计原则", "指出接口隔离与单一职责的区别", "如果新增一个功能必须反复修改旧类，这主要违背了哪条原则"),
    ),
    "污水池反模式": prompt_variants(
        ("指出什么是污水池反模式", "说明它会导致什么问题", "给出一个能看出该反模式的系统现象"),
        ("指出污水池反模式在分层系统中通常表现为什么现象", "说明它为什么会削弱层间边界", "给出一个整改方向"),
        ("从职责混杂角度说明污水池反模式的危害", "指出代码或模块层面的判别线索", "说明如何通过重新分层降低风险"),
    ),
    "表现层层次架构": prompt_variants(
        ("分别写出 MVC、MVP、MVVM 的职责分工", "比较三者的核心差异", "各举一个更贴近它的实现特征"),
        ("指出 MVC 中 View、Controller、Model 的典型职责", "说明 MVP 中 Presenter 为什么更适合测试", "指出 MVVM 中双向绑定解决了什么问题"),
        ("比较 MVC、MVP、MVVM 在耦合度上的差异", "分别说明 View 与业务逻辑之间由谁承担协调责任", "如果系统通过双向绑定驱动视图更新，更接近哪一种"),
    ),
    "容器和容器编排技术": prompt_variants(
        ("说明容器与虚拟机的主要差异", "指出容器编排要解决的核心问题", "写出容器编排常见的管理任务"),
        ("从资源隔离、启动速度、镜像复用 3 个角度比较容器与虚拟机", "说明为什么容器集群需要编排系统", "指出编排系统常负责的 2 类自动化能力"),
        ("指出容器编排在服务发现、伸缩、故障恢复上的作用", "说明镜像、容器、Pod 三者的关系", "给出一个适合上编排平台的业务场景"),
    ),
    "容器运维指令": prompt_variants(
        ("分别写出 Docker 查看类命令", "分别写出 Kubernetes 查看/日志/删除/更新命令", "分别说明查看状态、查看详情、查看日志、删除资源要用哪类命令"),
        ("写出 2 条 Docker 查看容器或镜像状态的命令", "写出 2 条 Kubernetes 查看 Pod 或日志的命令", "说明 `describe` 和 `logs` 常用于区分什么问题"),
        ("指出 `kubectl get`、`kubectl describe`、`kubectl logs`、`kubectl delete` 各自用途", "补充一个镜像查看命令", "说明 `describe` 和 `logs` 分别更适合排查什么问题"),
    ),
    "UDDI、WSDL 和 SOAP": prompt_variants(
        ("分别写出 UDDI、WSDL、SOAP 的作用", "说明三者在 Web Service 中的配合关系", "说明三者里哪个负责找服务、哪个负责描述接口、哪个负责传消息"),
        ("指出服务注册、服务描述、消息传输分别对应哪个概念", "说明请求方调用 Web Service 时大致经过哪些环节", "指出 WSDL 中通常会写到哪些接口信息"),
        ("从“找服务、看接口、发消息”三个动作映射到 UDDI、WSDL、SOAP", "说明 SOAP 报文通常承担什么职责", "比较它们与 REST 风格接口的差异"),
    ),
    "服务注册模式概念": prompt_variants(
        ("写出服务注册模式的核心角色", "说明各角色分别承担的职责", "指出该模式主要解决的是什么问题"),
        ("分别指出服务提供者、注册中心、服务消费者在注册模式中的动作", "说明注册与发现的顺序", "指出注册中心宕机对系统的影响"),
        ("说明为什么微服务体系需要服务注册", "指出注册信息通常至少包含哪些字段", "按顺序写出一个消费方获取服务地址并发起调用的过程"),
    ),
    "九大必考质量属性": prompt_variants(
        ("写出九大质量属性", "分别说明性能、可用性、安全性、可修改性的关注点", "任选一种质量属性写出一个典型场景"),
        ("把质量属性按运行期与开发运维期做一个粗分", "任选 4 个质量属性，各写出一个典型需求描述", "指出性能和可伸缩性为什么不能混为一谈"),
        ("指出可用性、可靠性、可维护性的区别", "说明安全性通常会落到哪些设计措施", "给出一个质量属性与架构策略的一一对应例子"),
    ),
    "质量属性场景描述案例": prompt_variants(
        ("写出质量属性场景描述的 6 个要素", "说明这 6 个要素分别描述什么", "结合一种质量属性给出场景描述思路"),
        ("指出刺激源、刺激、环境、制品、响应、响应度量分别是什么", "说明为什么质量属性题常要求写到响应度量", "给出一个完整的可用性场景骨架"),
        ("用性能或安全性举例，补全一个 6 要素场景", "把这个场景中的响应度量单独写出来", "如果只写到响应、不写度量，这个场景还缺什么"),
    ),
    "非对称加密概念": prompt_variants(
        ("说明公钥和私钥各自的用途", "指出非对称加密适用的典型场景", "说明它不适合大数据量加密的原因"),
        ("指出加密解密与签名验签分别使用哪把密钥", "说明非对称加密为什么常和对称加密配合", "给出一个 HTTPS 中的使用场景"),
        ("比较非对称加密与对称加密在安全性和性能上的差异", "指出非对称加密更擅长解决什么问题", "说明误用同一把密钥会导致什么错误"),
    ),
    "非对称加密的应用场景": prompt_variants(
        ("写出非对称加密最常见的 2 到 3 个应用场景", "分别说明这些场景里公钥和私钥各自怎么用", "指出为什么它常和对称加密配合"),
        ("说明数字签名和数字信封分别属于非对称加密的哪类应用", "写出签名、验签、加密、解密分别使用哪把密钥", "给出一个 HTTPS 中的落位"),
        ("给出一个登录认证或报文传输场景", "说明这里为什么更适合用非对称加密而不是单独用对称加密", "再指出它的性能代价"),
    ),
    "对称加密概念": prompt_variants(
        ("指出对称加密的核心特点", "写出其适用场景", "比较它与非对称加密的主要差异"),
        ("说明加密和解密为什么使用同一把密钥", "指出对称加密更适合处理什么数据规模", "说明它的主要风险点是什么"),
        ("比较对称加密与非对称加密在速度、密钥管理上的差异", "给出一个适合对称加密的业务场景", "如果题目里明确说加密和解密使用同一把密钥，这对应哪一种"),
    ),
    "数字证书": prompt_variants(
        ("指出数字证书的作用", "说明数字证书中通常包含哪些关键信息", "指出它与公钥加密、数字签名的关系"),
        ("说明 CA 在数字证书体系中的角色", "指出证书至少要证明什么信息", "说明浏览器校验证书时在验证什么"),
        ("从身份绑定角度说明为什么需要数字证书", "指出证书、公钥、私钥、签名之间的联系", "给出一个证书失效后的风险"),
    ),
    "分区容错性": prompt_variants(
        ("指出 CAP 中 P 的含义", "说明分布式系统为什么必须考虑分区容错", "比较分区容错性与可用性的区别"),
        ("说明网络分区发生时系统会面临什么局面", "指出为什么跨节点通信不可靠时不能假设系统仍然像单机", "给出一个分区场景下的取舍"),
        ("比较 P 与 C、A 的关系", "说明为什么 P 往往不是可选项", "如果网络分区导致节点之间无法通信，系统接下来面临什么取舍"),
    ),
    "Lambda 架构实现": prompt_variants(
        ("写出 Lambda 架构的三个层次", "分别说明批处理层、加速层、服务层的职责", "指出它适合的典型场景"),
        ("说明批处理层和速度层各自产生什么结果", "指出服务层为什么要把两边结果对外统一", "给出一个需要实时加离线分析并存的场景"),
        ("比较 Lambda 三层之间的数据流向", "指出 Lambda 架构为什么复杂", "说明它相对纯实时方案的优势"),
    ),
    "Lambda VS Kappa": prompt_variants(
        ("比较 Lambda 与 Kappa 的处理思路", "比较两者在复杂度上的差异", "指出各自更适合的场景"),
        ("指出 Lambda 为什么有双链路", "说明 Kappa 为什么强调统一流式处理", "比较两者在历史重算上的差异"),
        ("从实时性、实现复杂度、维护成本 3 个角度比较 Lambda 与 Kappa", "给出各自一个更适合的业务场景", "如果系统只有一条流式链路并依靠重放日志重算历史数据，这更接近哪一种"),
    ),
    "Lambda 架构优缺点": prompt_variants(
        ("从实时性角度说明其优缺点", "从历史数据处理能力角度说明其优缺点", "从维护成本角度说明其优缺点"),
        ("指出 Lambda 为什么兼顾实时与离线", "说明它为什么容易带来代码和链路重复", "给出一个采用它的前提条件"),
        ("从结果准确性、开发复杂度、运维复杂度 3 个角度分析 Lambda", "说明什么时候不值得上 Lambda", "如果团队人数少且维护预算紧张，还要不要上 Lambda，为什么"),
    ),
    "Kappa 架构的优缺点": prompt_variants(
        ("从实时处理角度说明 Kappa 架构的优点和缺点", "从历史数据处理能力角度说明其优点和缺点", "从系统复杂度或维护成本角度说明其优点和缺点"),
        ("说明 Kappa 统一流式链路的好处", "指出它在历史回放或重算上的代价", "给出一个更适合 Kappa 的场景"),
        ("从架构简化角度说明 Kappa 的优势", "从批量纠错角度说明 Kappa 的限制", "比较它与 Lambda 在代码维护上的不同"),
    ),
    "领域与子域": prompt_variants(
        ("指出什么是领域", "指出什么是子域", "结合一个业务系统场景说明为什么要先划分子域"),
        ("说明核心域、支撑域、通用域的区别", "指出子域划分通常依据什么业务边界", "给出一个业务系统中 3 个可能的子域"),
        ("说明为什么领域建模前不能直接按部门拆系统", "指出子域划分对后续限界上下文的作用", "举例说明错误划分子域会带来什么问题"),
    ),
    "层次架构简介": prompt_variants(
        ("写出层次架构常见的层次划分", "说明上层和下层之间通常如何调用", "说明为什么一般不建议跨层访问"),
        ("指出表示层、业务逻辑层、数据访问层分别负责什么", "写出一次请求从界面到数据层的流转过程", "如果业务规则直接写到界面层，会带来什么问题"),
        ("结合案例说明层次架构一般用在哪类系统中", "写出层与层之间的依赖方向", "说明层次划分过粗会出现什么问题"),
    ),
    "系统架构评估方法": prompt_variants(
        ("写出 ATAM、SAAM 各自关注什么", "说明架构评估为什么要先明确质量属性", "给出一个适合做架构评估的场景"),
        ("指出做系统架构评估通常要准备哪些输入材料", "写出评估过程中要识别的风险点或敏感点", "说明评估结论一般如何输出"),
        ("结合一个系统说明为什么要在设计阶段做架构评估", "写出评估时至少要比较的两个备选方案或决策点", "如果只看功能不看质量属性，会漏掉什么问题"),
    ),
    "质量属性场景描述的语言": prompt_variants(
        ("写出质量属性场景描述的 6 个要素", "分别说明这 6 个要素各表示什么", "说明为什么响应度量不能省略"),
        ("以秒杀场景为例，分别补出刺激源、刺激、环境、制品、响应、响应度量", "指出其中哪一项负责把需求写成可度量形式", "如果只有响应没有度量，这个场景还差什么"),
        ("给出一个可用性或性能需求", "按六要素场景模型把它改写完整", "再指出其中哪一项最容易和其他项混淆"),
    ),
    "架构权衡分析方法 ATAM": prompt_variants(
        ("写出 ATAM 的 4 个主要阶段", "说明 ATAM 主要关注哪 4 类质量属性", "指出它与 SAAM 相比多了什么核心工具"),
        ("说明什么是效用树", "写出效用树从树根到叶子通常包含哪些层次", "再说明场景优先级一般如何表示"),
        ("给出一个系统评估场景", "说明 ATAM 中应该如何识别敏感点、权衡点和风险点", "如果两个质量属性目标冲突，应在哪一步体现权衡"),
    ),
    "系统架构原则": prompt_variants(
        ("写出大数据系统设计常见的 5 个原则", "任选 3 个原则说明其含义", "各举一个对应的设计动作"),
        ("分别说明分布式环境、模块化设计、数据分区、并行处理为什么重要", "再指出它们分别主要改善哪一类能力", "给出一个和访问控制或审计日志相关的设计点"),
        ("给出一个大数据系统场景", "说明这里更应该优先考虑可扩展、可管理还是数据安全", "再写出支撑这个原则的一个具体做法"),
    ),
    "Lambda 分层介绍": prompt_variants(
        ("写出 Lambda 架构的 3 层", "分别说明批处理层、加速层、服务层的职责", "指出每一层常见的支撑技术"),
        ("说明批处理层和加速层为什么要分开设计", "写出服务层对外提供什么能力", "如果没有加速层，系统最先缺掉什么能力"),
        ("比较批处理层和加速层在处理数据范围、延迟和复杂度上的差异", "说明加速层的数据为什么还要持续写回批处理层", "给出一个适合 Lambda 的业务场景"),
    ),
    "应用编排": prompt_variants(
        ("说明应用编排的职责", "说明它与领域层业务规则的边界", "结合支付订单说明一次典型编排流程"),
        ("指出应用服务通常负责哪些跨聚合或跨领域动作", "说明为什么不应把核心业务规则全塞进编排层", "给出一个订单支付的编排步骤"),
        ("比较应用编排与领域服务的关注点", "指出编排层常见的输入输出", "说明编排过重会出现什么问题"),
    ),
    "可用性": prompt_variants(
        ("指出 CAP 中 A 的含义", "说明为什么返回旧数据也可能算可用", "比较可用性与一致性的差异"),
        ("说明可用性关注的是哪类外部观察结果", "指出节点故障时为了保可用通常会做什么取舍", "给出一个牺牲强一致换可用的例子"),
        ("比较高可用与高可靠的区别", "说明为什么超时、降级、兜底也属于可用性策略", "再写出 2 个常见的可用性措施"),
    ),
    "刚性事务 2PC": prompt_variants(
        ("写出 2PC 的两个阶段", "分别说明协调者和参与者在每个阶段的动作", "指出 2PC 的主要缺点"),
        ("指出 prepare 阶段参与者要做什么", "指出 commit/rollback 阶段各节点如何动作", "说明协调者故障为什么会带来阻塞"),
        ("从一致性保障角度说明 2PC 的价值", "指出它对可用性和性能的影响", "给出一个不适合用 2PC 的场景"),
    ),
    "数据分区": prompt_variants(
        ("指出什么是数据分区", "比较数据分区与数据分片的差异", "说明题目中按时间或范围拆分通常更偏向哪个概念"),
        ("分别举例说明按范围、按哈希、按时间做分区", "指出分区设计首先要看什么访问特征", "说明分区不合理会导致什么问题"),
        ("比较逻辑分区与物理分布的关系", "说明为什么热点数据会破坏分区效果", "指出一个分区键选择失误的例子"),
    ),
    "主从复制": prompt_variants(
        ("说明主从复制要解决的问题", "指出主节点与从节点各自职责", "说明复制延迟带来的影响"),
        ("写出主从复制建立连接后的关键动作", "指出主节点和从节点分别保存什么角色信息", "说明为什么读写分离会受复制延迟影响"),
        ("比较主从复制与分片扩展解决的问题差异", "说明主从复制为什么更偏向高可用和读扩展", "举出一个由复制延迟带来的系统现象"),
    ),
    "Redis 事务": prompt_variants(
        ("说明 Redis 事务的执行机制", "指出它解决了什么问题", "比较它与关系型数据库事务的差异"),
        ("写出 MULTI、EXEC、DISCARD 的作用", "说明 Redis 事务为什么不提供传统意义上的回滚", "说明它和关系型数据库事务最容易混淆的地方"),
        ("比较 Redis 事务与数据库 ACID 事务在隔离性上的差异", "说明 WATCH 在哪里发挥作用", "给出一个适合使用 Redis 事务的场景"),
    ),
    "Cluster 模式": prompt_variants(
        ("说明 Redis Cluster 为什么引入哈希槽", "指出 Cluster 解决了哪些问题", "说明它与主从/哨兵的差异"),
        ("指出哈希槽分配和节点扩缩容之间的关系", "说明 Cluster 如何兼顾分片与高可用", "给出一个适合用 Cluster 的场景"),
        ("比较 Cluster、主从、哨兵三者解决问题的范围", "说明 Cluster 为什么不只是“多主从”", "如果题目要求同时完成数据分片和高可用，对应哪一种"),
    ),
    "相关性算法": prompt_variants(
        ("写出 ElasticSearch 常见相关性算法", "说明 TF-IDF 与 BM25 的主要差异", "指出影响相关性得分的常见因素"),
        ("说明词频、逆文档频率分别刻画什么", "指出 BM25 为什么通常比 TF-IDF 更稳", "给出一个影响打分结果的字段设置因素"),
        ("比较 TF-IDF 与 BM25 对高频词的处理差异", "说明字段长度为什么会影响相关性", "指出调优相关性时常看的 2 个方向"),
    ),
    "热 Key": prompt_variants(
        ("指出什么是热 Key", "说明它为什么会把系统压力集中到少数节点", "给出一个典型出现热 Key 的业务场景"),
        ("写出热 Key 产生的 2 到 3 个常见原因", "说明它会带来哪些系统现象", "给出一个常见治理手段"),
        ("如果某个商品详情或排行榜请求突然暴涨，说明这是不是热 Key 问题", "写出排查热 Key 时常看的现象", "再给出一种缓解方案"),
    ),
    "ES 与传统关系型数据库的区别": prompt_variants(
        ("从数据结构角度比较 ES 和关系型数据库", "从核心能力角度比较全文检索、事务支持、扩展性的差异", "分别指出两者更适合的典型场景"),
        ("指出 ES 的倒排索引解决了什么问题", "说明关系型数据库擅长什么类型的查询和事务处理", "给出一个两者配合使用的场景"),
        ("从查询方式、写入一致性、扩展方式 3 个角度比较 ES 与关系库", "指出何时不应该拿 ES 取代关系库", "说明案例题里常见的系统落位"),
    ),
    "分词原理": prompt_variants(
        ("说明什么是分词", "分别指出分词器和倒排索引的作用", "说明分词对检索效果的影响"),
        ("指出索引时分词和搜索时分词各自发生在什么阶段", "说明为什么分词结果会影响召回率和准确率", "给出一个中文分词不当导致检索异常的例子"),
        ("说明倒排索引里通常记录什么信息", "指出分词器至少做了哪些基础处理", "比较细粒度分词与粗粒度分词对检索的影响"),
    ),
    "索引建立注意事项": prompt_variants(
        ("指出建立索引时需要重点考虑的因素", "说明哪些场景不适合盲目建立索引", "给出一个典型的索引设计失误"),
        ("说明索引为什么不是越多越好", "指出高频更新字段建索引会带来什么代价", "给出一个联合索引设计时的注意点"),
        ("从查询条件、排序方式、更新代价 3 个角度说明索引设计", "指出一个看似合理但实际低效的索引方案", "说明为什么要结合查询模式建索引"),
    ),
    "BSON": prompt_variants(
        ("说明 BSON 与 JSON 的关系", "指出 BSON 相比 JSON 的增强点", "说明 MongoDB 为什么适合使用 BSON"),
        ("指出 BSON 对日期、二进制、对象 ID 的支持意味着什么", "说明 BSON 与 JSON 在存储和遍历上的差别", "给出一个 BSON 更合适的场景"),
        ("比较 BSON 和 JSON 在数据类型丰富度上的差异", "说明为什么 MongoDB 需要比 JSON 更强的类型表达", "举出 BSON 比 JSON 多支持的一种数据类型并说明用途"),
    ),
    "GeoJSON": prompt_variants(
        ("指出 GeoJSON 是什么格式", "写出 GeoJSON 常见几何对象", "说明它在 MongoDB 中的主要用途"),
        ("写出 Point、LineString、Polygon 至少各表示什么几何对象", "说明 GeoJSON 中坐标通常如何表达", "指出 MongoDB 使用 GeoJSON 主要为了配合什么能力"),
        ("说明 GeoJSON 文档至少包含哪两个核心字段", "指出地理空间查询为什么需要统一几何表达", "给出一个附近检索或范围检索的例子"),
    ),
    "分片集群": prompt_variants(
        ("指出分片集群主要解决的问题", "说明分片集群的核心组成与基本机制", "指出它与单机扩容或主从复制的差异"),
        ("写出分片集群中路由、配置、数据分片节点各自职责", "说明一次查询请求大致如何路由", "指出为什么它主要解决容量和吞吐问题"),
        ("比较分片集群与主从复制在目标上的差异", "说明片键选择为什么关键", "给出一个不合理片键导致热点的例子"),
    ),
    "面向架构评估的质量属性": prompt_variants(
        ("写出架构评估中常考的质量属性", "任选 3 个质量属性说明关注点", "任选一种质量属性说明如何落到场景描述"),
        ("说明为什么质量属性评估不能只写名词", "指出性能、可用性、安全性分别常落到哪些架构策略", "给出一个可修改性的场景描述方向"),
        ("比较功能需求与质量属性需求的表达差异", "指出质量属性在架构评估中的作用", "说明题目为什么常要求写刺激、响应和度量"),
    ),
    "智能体简介": prompt_variants(
        ("指出智能体的本质是什么", "写出其“决策-行动-反馈”闭环包含哪些关键能力", "比较智能体与聊天机器人或普通对话式模型的区别"),
        ("说明智能体为什么不仅仅是会对话的模型", "指出环境感知、任务规划、工具调用分别承担什么作用", "给出一个典型的智能体任务场景"),
        ("比较智能体与工作流脚本的差异", "说明智能体为什么需要反馈回路", "如果系统会自主拆任务、调用工具、根据结果调整下一步，这更接近什么"),
    ),
    "智能体架构": prompt_variants(
        ("写出智能体架构的核心组成", "分别说明感知、规划、执行、记忆各自负责什么", "写出一次从接收任务到完成交付的处理链路"),
        ("说明为什么智能体架构不等于单次问答", "指出工具调用和环境反馈在其中分别起什么作用", "如果没有记忆或反馈回路，会直接影响什么能力"),
        ("给出一个需要多步决策的任务场景", "说明为什么更适合用智能体架构", "再写出其中至少两个需要协作的组件"),
    ),
    "规划-执行模式": prompt_variants(
        ("说明规划-执行模式的基本思路", "指出它适合的任务类型", "说明执行过程中计划与现实不一致时如何处理"),
        ("指出规划阶段通常产出什么", "说明执行阶段为什么可以按计划拆成多个子任务", "给出一个适合规划-执行模式的长任务例子"),
        ("比较规划-执行模式与 ReAct 的观察时机差异", "说明规划过细会带来什么问题", "指出什么时候需要中途重规划"),
    ),
    "ReAct 模式": prompt_variants(
        ("指出 ReAct 中 Reason 与 Act 分别指什么", "说明 ReAct 为什么适合边做边看的任务", "比较 ReAct 与规划-执行模式的差异"),
        ("说明 ReAct 中“想一步、做一步、看一步”的循环是什么", "指出观察反馈在 ReAct 里的作用", "给出一个比纯规划更适合 ReAct 的任务"),
        ("比较 ReAct 与单次规划执行在信息不确定环境下的差异", "说明 ReAct 为什么常结合工具调用", "指出它的一个典型局限"),
    ),
}


def comparison_prompt_variants(title: str) -> list[dict[str, str]]:
    if "和" in title and "、" not in title and " / " not in title:
        parts = [part.strip() for part in title.split("和") if part.strip()]
        if len(parts) == 2:
            left, right = parts
            return prompt_variants(
                (f"分别写出 {left} 和 {right} 的含义", f"说明 {left} 与 {right} 的关系", f"各举一个 {left} 或 {right} 在系统中的例子"),
                (f"指出 {left} 主要回答什么问题", f"指出 {right} 主要回答什么问题", "说明二者为什么不能混写"),
                (f"给出一个安全或架构场景", f"说明这里应先写 {left} 还是先写 {right}", "再补充对应的实现或保障手段"),
            )
    if "VS" in title:
        left, right = [part.strip() for part in title.split("VS", 1)]
        return prompt_variants(
            (f"分别说明 {left} 和 {right} 的基本思路", "比较二者在实现复杂度或维护成本上的差异", "指出二者分别适用的场景"),
            (f"从核心目标角度比较 {left} 和 {right}", "从实现链路角度比较二者差异", f"给出一段业务约束，说明更适合选 {left} 还是 {right}"),
            (f"比较 {left} 和 {right} 在实时性或扩展性上的差异", "说明两者各自更适合的业务背景", "指出选型时优先考虑的约束"),
        )
    if "对比" in title:
        subject = title.replace("对比", "").strip(" /")
        parts = [part.strip() for part in re.split(r"[、/]", subject) if part.strip()]
        if len(parts) >= 2:
            joined = "、".join(parts)
            return prompt_variants(
                (f"分别说明 {joined} 的基本含义", "指出它们的核心差异", "各举一个更适合它的业务场景"),
                (f"从实现机制角度比较 {joined}", "从运维或维护成本角度比较它们", "写出一组描述，并判断分别对应哪一个"),
                (f"说明 {joined} 分别主要解决什么问题", "指出各自典型的输入输出或结构特征", "给出一个选型示例"),
            )
    if "区别" in title:
        subject = title.replace("的区别", "").replace("区别", "").strip(" /")
        parts = [part.strip() for part in re.split(r"[和/、]", subject) if part.strip()]
        if len(parts) >= 2:
            left, right = parts[:2]
            return prompt_variants(
                (f"说明 {left} 和 {right} 的核心区别", "从实现机制角度展开比较", "各举一个更适合它的业务场景"),
                (f"指出 {left} 与 {right} 在目标上的不同", "分别写出一道描述，更符合其中哪一个", "给出一个容易混淆的例子"),
                (f"比较 {left} 与 {right} 在部署或维护成本上的差异", "说明二者对业务的影响不同体现在哪", "给出一段业务要求，判断更适合哪一个"),
            )
    return []


def generic_prompt_variants(title: str) -> list[dict[str, str]]:
    if "索引" in title:
        return prompt_variants(
            (f"说明 {title} 中至少包含哪两类核心信息", "指出它建立或查询时最关键的动作", "说明它对检索或查询性能的直接影响"),
            (f"指出 {title} 主要解决什么问题", "写出它建立或查询时依赖的关键结构或步骤", "给出一个设计或使用不当的后果"),
            (f"比较 {title} 与顺序扫描或普通查询方式的差异", "说明它更适合什么类型的查询", "如果查询条件、排序方式和索引设计不匹配，会出现什么现象"),
        )
    if "分离" in title:
        return prompt_variants(
            (f"指出 {title} 分开的两类职责分别是什么", "说明这样拆开之后请求通常如何流转", "指出一个典型风险点"),
            (f"说明 {title} 主要为了缓解什么瓶颈", "分别说明一次读请求和一次写请求通常怎么走", "如果从库延迟或链路故障，会出现什么现象"),
            (f"比较 {title} 与主从复制或分库分表的关系", "说明它们解决问题的侧重点差异", "给出一个更适合采用它的业务场景"),
        )
    if "分析" in title:
        return prompt_variants(
            (f"指出 {title} 主要分析哪几类对象或问题", "写出分析时通常要产出的 2 到 3 类结果", "给出一个具体案例说明如何下手"),
            (f"结合一个案例说明 {title} 的分析顺序", "指出分析结果里需要包含的关键术语", "如果把分析结论直接写成设计方案，问题出在哪"),
            (f"结合场景说明 {title} 的基本步骤或思路", "指出产出物或结论通常是什么", "说明为什么这一步对后续设计重要"),
        )
    if any(keyword in title for keyword in ("流程", "步骤", "阶段")):
        return prompt_variants(
            (f"写出 {title} 的主要步骤或阶段", "分别说明各步骤或阶段的作用", "如果漏掉其中一步，后续哪个结果拿不到"),
            (f"说明 {title} 的起点和终点分别是什么", "指出中间最关键的 2 个环节", "说明步骤顺序为什么不能颠倒"),
            (f"结合案例补全 {title} 里的 3 个关键动作", "说明每个动作由谁触发", "指出一个常见异常点"),
        )
    if any(keyword in title for keyword in ("指令", "命令")):
        return prompt_variants(
            (f"写出 {title} 常见查看类命令", "写出执行/删除/更新类命令", "判断给定命令属于哪一类用途"),
            (f"写出 2 条和 {title} 相关的状态查看命令", "写出 2 条操作类命令", "说明哪条命令最容易和日志查看混淆"),
            (f"指出 {title} 相关命令里最常见的 3 个动词", "说明每个动词一般配合什么对象", "给出一个错误命令使用场景"),
        )
    if any(keyword in title for keyword in ("事务", "一致性", "复制", "分片", "持久化")):
        return prompt_variants(
            (f"说明 {title} 主要解决的问题", "指出其关键机制或核心流程", "说明实现不当会带来的问题"),
            (f"指出 {title} 涉及的核心角色或组件", "说明这些角色如何配合", "给出一个执行失败或延迟时的系统现象"),
            (f"写出 {title} 的关键步骤或状态变化", "说明哪个环节最容易出问题", "出现问题后系统通常会表现出什么现象"),
        )
    if any(keyword in title for keyword in ("图", "视图")):
        return prompt_variants(
            (f"写出 {title} 的核心元素", "说明该图或视图的主要作用", "说明图中箭头或关系的判别依据"),
            (f"指出 {title} 主要表达的对象或关系", "说明图上两类关键连线或符号分别表示什么", "给出一个适合用它表达的建模场景"),
            (f"结合案例说明 {title} 一般用来回答什么问题", "指出图上两类关键连线或符号分别表示什么", "按顺序写出一个使用它建模的步骤"),
        )
    if "优缺点" in title:
        return prompt_variants(
            (f"从 3 个方面说明 {title} 的优点", f"从相同角度说明 {title} 的缺点", "指出什么情况下不适合采用它"),
            (f"从性能、复杂度、维护成本角度分析 {title}", "说明它最明显的短板是什么", "给出一个更适合使用它的场景"),
            (f"指出 {title} 带来的收益主要体现在哪里", "说明这些收益背后的代价", "给出一个选型判断标准"),
        )
    if any(keyword in title for keyword in ("概念", "简介", "定义")):
        return prompt_variants(
            (f"指出 {title} 的准确定义", f"写出 {title} 落地时必须出现的 2 到 3 个关键点", "举出一个它在系统中的使用场景"),
            (f"说明 {title} 要解决的直接问题", "给出一个具体情境，说明此时为什么需要它", "写出它落地时至少包含的两个关键点"),
            (f"结合案例说明 {title} 一般落在哪个位置或阶段", "指出它通常包含哪些关键对象", "分别说明这些对象之间是什么关系"),
        )
    if "体系结构风格" in title:
        return prompt_variants(
            (f"写出 {title} 的核心构件", "说明这些构件之间通过什么方式连接", "写出一次典型处理过程"),
            (f"指出 {title} 的输入、处理和输出分别落在哪", "说明控制流或数据流如何传递", "给出一个适合采用它的业务场景"),
            (f"结合案例说明 {title} 中最关键的一层或一个部件", "说明它承担什么职责", "指出一个容易出现瓶颈的位置"),
        )
    if "风格" in title:
        return prompt_variants(
            (f"写出 {title} 的核心构件或处理单元", "说明这些构件之间如何连接或传递数据", "给出一个适合采用它的业务场景"),
            (f"指出 {title} 的输入、处理和输出分别落在哪", "说明它最强调的结构特征", "如果某个环节堵塞，最先影响哪一部分"),
            (f"结合案例说明 {title} 一般如何分层或分工", "写出一次典型处理链路", "指出一个容易出现性能瓶颈的位置"),
        )
    if "架构" in title:
        return prompt_variants(
            (f"写出 {title} 的关键组成", "分别说明每个组成承担什么职责", "写出一次从输入到输出的处理链路"),
            (f"给出一个业务场景，说明为什么会选 {title}", "写出其中承担协调、存储、执行或路由的部分", "如果缺少其中一层或一类组件，会直接影响什么"),
            (f"说明 {title} 主要解决哪类问题", "写出它通常依赖的前提条件", "给出一个部署或运维上的限制"),
        )
    if "模式" in title:
        return prompt_variants(
            (f"写出 {title} 的参与者或组成部分", "分别说明它们的职责", "按顺序写出一次典型交互过程"),
            (f"说明 {title} 主要解决什么问题", "写出它成立所依赖的前提条件", "给出一个使用不当会出现的现象"),
            (f"结合场景说明 {title} 适合放在系统的哪一层或哪一环", "写出它与上下游对象如何协作", "指出一个常见故障点"),
        )
    if "设计" in title:
        return prompt_variants(
            (f"说明 {title} 要解决的问题", "写出其中最关键的 2 到 3 个设计动作", "如果不这样设计，系统最容易出现什么问题"),
            (f"结合场景说明 {title} 的输入和输出分别是什么", "写出设计过程中最关键的约束", "给出一个设计错误的例子"),
            (f"写出 {title} 涉及的关键对象或模块", "说明它们之间如何协作", "指出一个需要重点权衡的点"),
        )
    if "原理" in title:
        return prompt_variants(
            (f"写出 {title} 的核心概念", "说明它的处理过程或计算过程", "指出结果受哪类因素影响"),
            (f"结合场景说明 {title} 从输入到输出如何变化", "写出其中最关键的一步", "如果该步骤处理错误，会出现什么结果"),
            (f"指出 {title} 解决的直接问题", "写出它依赖的关键结构或数据", "给出一个使用不当的例子"),
        )
    if any(keyword in title for keyword in ("模型", "模式", "架构", "设计", "原理")):
        return prompt_variants(
            (f"指出 {title} 要解决的具体问题", f"写出 {title} 的关键组成或角色", "说明这些组成或角色如何串起来完成一次处理"),
            (f"给出一个具体业务场景，说明为什么会选 {title}", "说明它的组件或角色之间如何配合", "如果缺少其中某一环，会直接影响什么"),
            (f"写出 {title} 的关键输入、处理和输出", "说明采用它需要满足什么前提", "指出一个部署或实现上的限制"),
        )
    return prompt_variants(
        (f"写出 {title} 的关键对象、条件或约束", "分别说明这些对象、条件或约束在系统里对应什么", "举出一个对象或约束在系统中的对应实例"),
        (f"结合场景说明 {title} 主要解决什么具体问题", "写出它依赖的核心对象、步骤或限制", "给出一个使用不当会出现的现象"),
        (f"给出一个具体业务情境，说明 {title} 应该怎样用", "写出它依赖的前提条件或核心步骤", "给出一个使用不当的后果"),
    )


def topic_prompt_variants(title: str) -> list[dict[str, str]]:
    if title in SPECIFIC_PROMPT_VARIANTS:
        return SPECIFIC_PROMPT_VARIANTS[title]

    compare_prompt = comparison_prompt_variants(title)
    if compare_prompt:
        return compare_prompt

    return generic_prompt_variants(title)


def recent_prompt_constraints(entry: dict[str, Any], today: date) -> tuple[set[str], bool]:
    recent_prompt_ids: set[str] = set()
    has_untracked_recent_question = False

    for item in entry.get("question_history", []):
        asked_days_ago = days_since(item.get("date"), today)
        if asked_days_ago is None or asked_days_ago >= PROMPT_COOLDOWN_DAYS:
            continue
        prompt_id = item.get("prompt_id")
        if prompt_id:
            recent_prompt_ids.add(prompt_id)
        else:
            has_untracked_recent_question = True

    for item in entry.get("history", []):
        asked_days_ago = days_since(item.get("date"), today)
        if asked_days_ago is None or asked_days_ago >= PROMPT_COOLDOWN_DAYS:
            continue
        prompt_id = item.get("prompt_id")
        if prompt_id:
            recent_prompt_ids.add(prompt_id)
        else:
            has_untracked_recent_question = True

    last_asked_days_ago = days_since(entry.get("last_asked"), today)
    if last_asked_days_ago is not None and last_asked_days_ago < PROMPT_COOLDOWN_DAYS and not (recent_prompt_ids or has_untracked_recent_question):
        has_untracked_recent_question = True

    return recent_prompt_ids, has_untracked_recent_question


def choose_prompt_variant(topic: dict[str, Any], entry: dict[str, Any], today: date, rng: random.Random) -> tuple[float, dict[str, str]] | None:
    variants = topic_prompt_variants(topic["title"])
    recent_prompt_ids, has_untracked_recent_question = recent_prompt_constraints(entry, today)
    if has_untracked_recent_question:
        return None

    usage_count: dict[str, int] = {}
    for item in entry.get("question_history", []):
        prompt_id = item.get("prompt_id")
        if prompt_id:
            usage_count[prompt_id] = usage_count.get(prompt_id, 0) + 1
    for item in entry.get("history", []):
        prompt_id = item.get("prompt_id")
        if prompt_id:
            usage_count[prompt_id] = usage_count.get(prompt_id, 0) + 1

    candidates: list[tuple[float, dict[str, str]]] = []
    for variant in variants:
        if variant["prompt_id"] in recent_prompt_ids:
            continue
        variant_score = max(0.5, 2.5 - usage_count.get(variant["prompt_id"], 0))
        variant_score += rng.random()
        candidates.append((variant_score, variant))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0]


def parent_topic_headings(bank: dict[str, Any]) -> set[str]:
    headings = [topic["heading"] for topic in all_topics(bank)]
    parents: set[str] = set()
    for heading in headings:
        prefix = f"{heading}."
        if any(other.startswith(prefix) for other in headings):
            parents.add(heading)
    return parents


def run_pdftotext(pdf_path: Path, start_page: int, end_page: int) -> str:
    result = subprocess.run(
        [
            "pdftotext",
            "-f",
            str(start_page),
            "-l",
            str(end_page),
            str(pdf_path),
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def clean_extracted_text(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = normalize_spaces(raw)
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if any(pattern in line for pattern in WATERMARK_PATTERNS):
            continue
        if re.fullmatch(r"[0-9]+", line):
            continue
        if re.fullmatch(r"[版盗备案封知识产权号]+", line):
            continue
        lines.append(line)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw_pages = result.stdout.split("\f")
    pages = [clean_extracted_text(page) for page in raw_pages]
    while pages and not pages[-1]:
        pages.pop()
    return pages


def parse_real_case_categories(vault: Path) -> list[dict[str, Any]]:
    pdf_path = vault / REAL_CASE_PDF_RELATIVE_PATH
    toc_text = run_pdftotext(pdf_path, 1, 10)
    rows: list[dict[str, Any]] = []

    for raw in toc_text.splitlines():
        line = normalize_spaces(raw)
        if not line:
            continue
        match = re.match(r"^(.+?)\s+(\d+)$", line)
        if not match:
            continue
        title = normalize_spaces(match.group(1))
        page = int(match.group(2))
        if title in REAL_CASE_TOC_SKIP_TITLES or title.startswith("注："):
            continue
        rows.append({"category": title, "start_page": page})

    rows.sort(key=lambda item: item["start_page"])
    for index, row in enumerate(rows):
        next_page = rows[index + 1]["start_page"] if index + 1 < len(rows) else None
        row["end_page"] = None if next_page is None else next_page - 1
    return rows


def category_for_page(page_no: int, categories: list[dict[str, Any]]) -> str:
    for row in categories:
        end_page = row.get("end_page")
        if page_no >= row["start_page"] and (end_page is None or page_no <= end_page):
            return row["category"]
    return categories[-1]["category"] if categories else "未分类"


def page_for_offset(offset: int, offsets: list[int]) -> int:
    return bisect.bisect_right(offsets, offset)


def parse_real_case_subject(section_text: str) -> str:
    for pattern in REAL_CASE_SUBJECT_PATTERNS:
        match = pattern.search(section_text)
        if match:
            return normalize_spaces(match.group(1))
    return "案例真题"


def trim_problem_body(text: str) -> str:
    body = text
    for marker in ("思路解析", "答案-问题", "答案 - 问题"):
        if marker in body:
            body = body.split(marker, 1)[0]
    body = re.sub(r"第\s*\d+\s*页", " ", body)
    return normalize_spaces(body)


def extract_real_case_stem(section_text: str) -> str:
    match = re.search(r"【说明】(.*?)(?:问题[（(][一二三四123456789]+[）)])", section_text, flags=re.S)
    if match:
        stem = trim_problem_body(match.group(1))
        return stem[:220]

    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    fallback_lines: list[str] = []
    for line in lines[1:]:
        if REAL_CASE_PROBLEM_PATTERN.match(line) or line.startswith("思路解析") or line.startswith("答案-问题"):
            break
        fallback_lines.append(line)
    stem = trim_problem_body(" ".join(fallback_lines))
    return stem[:220]


def extract_real_case_problems(section_text: str) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    matches = list(REAL_CASE_PROBLEM_PATTERN.finditer(section_text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        prompt = trim_problem_body(section_text[match.end() : end])
        if not prompt:
            continue
        problems.append(
            {
                "index": match.group(1),
                "prompt": prompt[:220],
            }
        )
    return problems


def compact_search_text(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).lower()


def text_ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def parse_real_case_bank(vault: Path) -> dict[str, Any]:
    pdf_path = vault / REAL_CASE_PDF_RELATIVE_PATH
    pages = extract_pdf_pages(pdf_path)
    full_text = "\f".join(pages)
    offsets: list[int] = []
    position = 0
    for page in pages:
        offsets.append(position)
        position += len(page) + 1

    categories = parse_real_case_categories(vault)
    matches = list(REAL_CASE_TITLE_PATTERN.finditer(full_text))
    items: list[dict[str, Any]] = []

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(full_text)
        section_text = clean_extracted_text(full_text[match.start() : end])
        year = int(match.group(1))
        month = int(match.group(2))
        question_no = int(match.group(3))
        start_page = page_for_offset(match.start(), offsets)
        end_page = page_for_offset(max(match.start(), end - 1), offsets)
        subject = parse_real_case_subject(section_text)
        stem_excerpt = extract_real_case_stem(section_text)
        problems = extract_real_case_problems(section_text)
        search_text = normalize_spaces(
            " ".join(
                [
                    subject,
                    stem_excerpt,
                    " ".join(problem["prompt"] for problem in problems),
                    section_text[:600],
                ]
            )
        )
        items.append(
            {
                "real_question_id": f"rq-{year}-{month:02d}-{question_no}",
                "year": year,
                "month": month,
                "question_no": question_no,
                "exam_label": f"{year}年{month}月系统架构真题-第{question_no}题",
                "category": category_for_page(start_page, categories),
                "subject": subject,
                "start_page": start_page,
                "end_page": end_page,
                "stem_excerpt": stem_excerpt,
                "problems": problems,
                "search_text": search_text,
                "body_text": section_text,
            }
        )

    return {
        "generated_at": date.today().isoformat(),
        "source_pdf": str(REAL_CASE_PDF_RELATIVE_PATH),
        "categories": categories,
        "items": items,
    }


def parse_bank(vault: Path) -> dict[str, Any]:
    pdf_path = vault / PDF_RELATIVE_PATH
    toc_text = run_pdftotext(pdf_path, 1, 10)

    chapter_pattern = re.compile(r"^(\d{1,2})\.\s+(.+?)\s+\.{2,}\s*(\d+)$")
    topic_pattern = re.compile(r"^(\d{1,2}(?:\.\d+)+)\.\s+(.+?)\s+\.{2,}\s*(\d+)$")

    chapters: dict[int, dict[str, Any]] = {}
    topic_rows: list[dict[str, Any]] = []
    cleaned_lines: list[str] = []

    for raw in toc_text.splitlines():
        line = normalize_spaces(raw)
        if not line or any(pattern in line for pattern in WATERMARK_PATTERNS):
            continue
        cleaned_lines.append(line)

    for line in cleaned_lines:
        chapter_match = chapter_pattern.match(line)
        if chapter_match:
            chapter_no = int(chapter_match.group(1))
            if chapter_no > 15:
                continue
            chapter_title, chapter_importance = clean_title(chapter_match.group(2))
            chapters[chapter_no] = {
                "chapter_no": chapter_no,
                "chapter_title": chapter_title,
                "chapter_importance": chapter_importance,
                "page": int(chapter_match.group(3)),
            }
    
    for line in cleaned_lines:
        if chapter_pattern.match(line):
            continue

        topic_match = topic_pattern.match(line)
        if not topic_match:
            continue

        heading = topic_match.group(1)
        chapter_no = int(heading.split(".")[0])
        if chapter_no > 15 or chapter_no not in chapters:
            continue
        title, importance = clean_title(topic_match.group(2))
        if should_skip_topic(title):
            continue
        depth = heading.count(".") + 1
        score = importance_score(importance) + depth
        topic_rows.append(
            {
                "chapter_no": chapter_no,
                "heading": heading,
                "title": title,
                "importance": importance,
                "page": int(topic_match.group(3)),
                "depth": depth,
                "score": score,
            }
        )

    topic_rows.sort(key=lambda item: (item["page"], item["heading"]))

    topics: list[Topic] = []
    for index, row in enumerate(topic_rows):
        next_page = topic_rows[index + 1]["page"] if index + 1 < len(topic_rows) else 201
        end_page = max(row["page"], next_page - 1)
        chapter = chapters[row["chapter_no"]]
        heading_token = row["heading"].replace(".", "_")
        topic_id = f"c{row['chapter_no']:02d}-{heading_token}"
        topics.append(
            Topic(
                topic_id=topic_id,
                chapter_no=row["chapter_no"],
                chapter_title=chapter["chapter_title"],
                chapter_importance=chapter["chapter_importance"],
                heading=row["heading"],
                title=row["title"],
                importance=row["importance"],
                page=row["page"],
                end_page=end_page,
                depth=row["depth"],
                score=row["score"],
                question_prompt=topic_prompt_variants(row["title"])[0]["question_prompt"],
            )
        )

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for topic in topics:
        grouped[topic.chapter_no].append(asdict(topic))

    ordered_chapters: list[dict[str, Any]] = []
    for chapter_no in sorted(chapters):
        chapter = chapters[chapter_no]
        ordered_chapters.append(
            {
                **chapter,
                "topics": grouped.get(chapter_no, []),
            }
        )

    return {
        "generated_at": date.today().isoformat(),
        "source_pdf": str(PDF_RELATIVE_PATH),
        "chapters": ordered_chapters,
    }


def default_state_entry(topic: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic_id": topic["topic_id"],
        "chapter_no": topic["chapter_no"],
        "chapter_title": topic["chapter_title"],
        "heading": topic["heading"],
        "title": topic["title"],
        "importance": topic["importance"],
        "page": topic["page"],
        "end_page": topic["end_page"],
        "ask_count": 0,
        "correct_count": 0,
        "partial_count": 0,
        "wrong_count": 0,
        "mastery": 0,
        "status": "new",
        "retired": False,
        "first_attempt_correct": None,
        "last_result": None,
        "last_asked": None,
        "last_prompt_id": None,
        "history": [],
        "question_history": [],
    }


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def all_topics(bank: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for chapter in bank["chapters"]:
        items.extend(chapter["topics"])
    return items


def ensure_state(bank: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    state = {
        "updated_at": date.today().isoformat(),
        "source_pdf": bank["source_pdf"],
        "topics": existing.get("topics", {}),
    }

    current_topics = {topic["topic_id"]: topic for topic in all_topics(bank)}
    for topic_id, topic in current_topics.items():
        if topic_id not in state["topics"]:
            state["topics"][topic_id] = default_state_entry(topic)
        else:
            for key in ("chapter_no", "chapter_title", "heading", "title", "importance", "page", "end_page"):
                state["topics"][topic_id][key] = topic[key]
            state["topics"][topic_id].setdefault("last_prompt_id", None)
            state["topics"][topic_id].setdefault("question_history", [])
            state["topics"][topic_id].setdefault("history", [])

    stale_ids = [topic_id for topic_id in state["topics"] if topic_id not in current_topics]
    for topic_id in stale_ids:
        state["topics"][topic_id]["archived"] = True

    return state


def chapter_stats(bank: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chapter in bank["chapters"]:
        items = [state["topics"][topic["topic_id"]] for topic in chapter["topics"] if topic["topic_id"] in state["topics"]]
        total = len(items)
        retired = sum(1 for item in items if item["retired"])
        reviewing = sum(1 for item in items if item["status"] == "reviewing")
        mastery = round(sum(item["mastery"] for item in items) / total, 2) if total else 0.0
        rows.append(
            {
                "chapter_no": chapter["chapter_no"],
                "chapter_title": chapter["chapter_title"],
                "total": total,
                "retired": retired,
                "reviewing": reviewing,
                "avg_mastery": mastery,
            }
        )
    return rows


def render_report(bank: dict[str, Any], state: dict[str, Any]) -> str:
    topics = [item for item in state["topics"].values() if not item.get("archived")]
    total = len(topics)
    retired = sum(1 for item in topics if item["retired"])
    reviewing = sum(1 for item in topics if item["status"] == "reviewing")
    new_items = sum(1 for item in topics if item["status"] == "new")
    wrong_items = sum(1 for item in topics if item["wrong_count"] > 0)

    lines = [
        "# 案例冲刺掌握情况",
        "",
        f"> 基于 `{STATE_PATH}` 自动生成",
        f"> 统计时间：{state['updated_at']}",
        "",
        "## 总览",
        "",
        f"- 知识点总数：{total}",
        f"- 已退休（首轮一次答对）：{retired}",
        f"- 正在复习池：{reviewing}",
        f"- 尚未抽到：{new_items}",
        f"- 出错过、仍可继续抽到：{wrong_items}",
        "",
        "## 章节状态",
        "",
        "| 章节 | 候选知识点 | 已退休 | 仍在复习 | 平均掌握度 |",
        "|---|---:|---:|---:|---:|",
    ]

    for row in chapter_stats(bank, state):
        lines.append(
            f"| {row['chapter_no']}. {row['chapter_title']} | {row['total']} | {row['retired']} | {row['reviewing']} | {row['avg_mastery']:.2f} |"
        )

    weak = sorted(
        (item for item in topics if not item["retired"]),
        key=lambda item: (-item["wrong_count"], item["mastery"], item["chapter_no"], item["heading"]),
    )[:15]

    lines.extend(
        [
            "",
            "## 当前优先补洞",
            "",
            "| 知识点 | 状态 | 错误次数 | 最后结果 |",
            "|---|---|---:|---|",
        ]
    )

    for item in weak:
        lines.append(
            f"| {item['heading']} {item['title']} | {item['status']} | {item['wrong_count']} | {item['last_result'] or '-'} |"
        )

    return "\n".join(lines) + "\n"


def refresh(vault: Path) -> None:
    bank = parse_bank(vault)
    real_case_bank = parse_real_case_bank(vault)
    existing_state = load_json(vault / STATE_PATH, {})
    state = ensure_state(bank, existing_state)
    save_json(vault / BANK_PATH, bank)
    save_json(vault / REAL_CASE_BANK_PATH, real_case_bank)
    save_json(vault / STATE_PATH, state)
    (vault / REPORT_PATH).write_text(render_report(bank, state), encoding="utf-8")


def load_bank_and_state(vault: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    bank_path = vault / BANK_PATH
    state_path = vault / STATE_PATH
    if not bank_path.exists() or not state_path.exists():
        refresh(vault)
    bank = load_json(bank_path, {})
    state = ensure_state(bank, load_json(state_path, {}))
    return bank, state


def load_real_case_bank(vault: Path) -> dict[str, Any]:
    bank_path = vault / REAL_CASE_BANK_PATH
    if not bank_path.exists():
        real_case_bank = parse_real_case_bank(vault)
        save_json(bank_path, real_case_bank)
        return real_case_bank
    return load_json(bank_path, {})


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def days_since(last_asked: str | None, today: date) -> int | None:
    asked_at = parse_iso_date(last_asked)
    if asked_at is None:
        return None
    return (today - asked_at).days


def related_real_case_queries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for item in items:
        prompt_lines = [re.sub(r"^（\d+）", "", line).strip() for line in item["question_prompt"].splitlines() if line.strip()]
        query_text = " ".join([item["title"], *prompt_lines])
        compact = compact_search_text(query_text)
        queries.append(
            {
                "title": item["title"],
                "prompt_id": item["prompt_id"],
                "query_text": query_text,
                "compact": compact,
                "bigrams": text_ngrams(compact, 2),
                "trigrams": text_ngrams(compact, 3),
            }
        )
    return queries


def score_real_case(item: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, Any]:
    search_text = item.get("search_text", "")
    compact = compact_search_text(search_text)
    search_bigrams = text_ngrams(compact, 2)
    search_trigrams = text_ngrams(compact, 3)
    score = 0.0
    matched_topics: list[str] = []
    exact_title_count = 0
    exact_phrase_count = 0

    for query in queries:
        topic_score = 0.0
        exact_title_hit = bool(query["title"] and query["title"] in search_text)
        if exact_title_hit:
            topic_score += 16
            exact_title_count += 1

        exact_line_hits = 0
        for line in [segment.strip() for segment in query["query_text"].split() if segment.strip()]:
            if len(line) >= 4 and line in search_text:
                topic_score += 5
                exact_line_hits += 1
        exact_phrase_count += exact_line_hits

        trigram_hits = len(query["trigrams"] & search_trigrams)
        bigram_hits = len(query["bigrams"] & search_bigrams)
        topic_score += min(trigram_hits, 18) * 1.2
        topic_score += min(bigram_hits, 24) * 0.35

        if exact_title_hit or exact_line_hits > 0 or topic_score >= 9:
            matched_topics.append(query["title"])
        score += topic_score

    score += len(set(matched_topics)) * 2.5
    score += min(item.get("year", 0), 2025) * 0.001
    return {
        "score": score,
        "matched_topics": matched_topics,
        "exact_title_count": exact_title_count,
        "exact_phrase_count": exact_phrase_count,
    }


def pick_related_real_cases(vault: Path, picked_items: list[dict[str, Any]], count: int = DEFAULT_REAL_CASE_COUNT) -> list[dict[str, Any]]:
    if count <= 0 or not picked_items:
        return []

    real_case_bank = load_real_case_bank(vault)
    queries = related_real_case_queries(picked_items)
    ranked: list[dict[str, Any]] = []

    for item in real_case_bank.get("items", []):
        details = score_real_case(item, queries)
        score = details["score"]
        if score <= 0:
            continue
        ranked.append(
            {
                **item,
                "related_score": round(score, 2),
                "matched_topics": details["matched_topics"],
                "exact_title_count": details["exact_title_count"],
                "exact_phrase_count": details["exact_phrase_count"],
            }
        )

    if not ranked:
        return []

    ranked.sort(
        key=lambda item: (
            item["exact_title_count"],
            item["exact_phrase_count"],
            len(set(item["matched_topics"])),
            item["related_score"],
            item["year"],
            item["question_no"],
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    covered_topics: set[str] = set()

    while ranked and len(selected) < count:
        best_index = 0
        best_value: tuple[float, int, int, int, float, int, int] | None = None
        for index, item in enumerate(ranked):
            new_topics = set(item["matched_topics"]) - covered_topics
            value = (
                30.0 if new_topics else 0.0,
                item["exact_title_count"],
                item["exact_phrase_count"],
                len(new_topics),
                item["related_score"],
                item["year"],
                item["question_no"],
            )
            if best_value is None or value > best_value:
                best_value = value
                best_index = index

        item = ranked.pop(best_index)
        if item["real_question_id"] in seen_ids:
            continue
        selected.append(item)
        seen_ids.add(item["real_question_id"])
        covered_topics.update(item["matched_topics"])
    return selected


def render_real_case_screenshots(vault: Path, real_case: dict[str, Any], today: str) -> list[str]:
    pdf_path = vault / REAL_CASE_PDF_RELATIVE_PATH
    output_dir = REAL_CASE_SCREENSHOT_DIR / today
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / real_case["real_question_id"]

    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(real_case["start_page"]),
            "-l",
            str(real_case["end_page"]),
            "-png",
            "-r",
            "150",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    paths = sorted(output_dir.glob(f"{real_case['real_question_id']}-*.png"))
    return [str(path.resolve()) for path in paths]


def attach_real_case_screenshots(vault: Path, real_cases: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    with_screenshots: list[dict[str, Any]] = []
    for item in real_cases:
        with_screenshots.append(
            {
                **item,
                "screenshot_paths": render_real_case_screenshots(vault, item, today),
            }
        )
    return with_screenshots


def pick_topics(
    vault: Path,
    seed: int | None,
    count: int = DEFAULT_PICK_COUNT,
    real_case_count: int = DEFAULT_REAL_CASE_COUNT,
) -> dict[str, Any]:
    bank, state = load_bank_and_state(vault)
    rng = random.Random(seed)
    today_obj = date.today()
    today = today_obj.isoformat()
    parent_headings = parent_topic_headings(bank)
    primary_chapter_candidates: list[tuple[dict[str, Any], list[tuple[float, dict[str, Any], dict[str, str]]]]] = []
    recent_chapter_candidates: list[tuple[dict[str, Any], list[tuple[float, dict[str, Any], dict[str, str]]]]] = []
    repeated_today_candidates: list[tuple[dict[str, Any], list[tuple[float, dict[str, Any], dict[str, str]]]]] = []

    for chapter in bank["chapters"]:
        fresh_candidates = []
        recent_topic_candidates = []
        repeated_candidates = []
        chapter_last_asked: date | None = None
        for topic in chapter["topics"]:
            topic_state = state["topics"][topic["topic_id"]]
            if topic_state["retired"]:
                continue
            if should_skip_topic(topic["title"]):
                continue
            if topic["heading"] in parent_headings:
                continue
            prompt_choice = choose_prompt_variant(topic, topic_state, today_obj, rng)
            if prompt_choice is None:
                continue
            asked_at = parse_iso_date(topic_state["last_asked"])
            if asked_at is not None and (chapter_last_asked is None or asked_at > chapter_last_asked):
                chapter_last_asked = asked_at
            score = topic["score"]
            if topic_state["wrong_count"] > 0:
                score += min(topic_state["wrong_count"] * 2, 6)
            if topic_state["ask_count"] == 0:
                score += 2
            if topic_state["status"] == "reviewing":
                score += 1
            prompt_score, prompt_variant = prompt_choice
            score += prompt_score
            asked_days_ago = days_since(topic_state["last_asked"], today_obj)
            if asked_days_ago == 0:
                target = repeated_candidates
            elif asked_days_ago is not None and asked_days_ago < TOPIC_COOLDOWN_DAYS:
                target = recent_topic_candidates
            else:
                target = fresh_candidates
            target.append((score, topic, prompt_variant))

        if fresh_candidates:
            fresh_candidates.sort(key=lambda item: item[0], reverse=True)
        if recent_topic_candidates:
            recent_topic_candidates.sort(key=lambda item: item[0], reverse=True)
        if repeated_candidates:
            repeated_candidates.sort(key=lambda item: item[0], reverse=True)

        chapter_gap = None if chapter_last_asked is None else (today_obj - chapter_last_asked).days
        if fresh_candidates:
            bucket = (
                recent_chapter_candidates
                if chapter_gap is not None and 0 < chapter_gap <= CHAPTER_COOLDOWN_DAYS
                else primary_chapter_candidates
            )
            bucket.append((chapter, fresh_candidates))
        elif recent_topic_candidates:
            recent_chapter_candidates.append((chapter, recent_topic_candidates))
        elif repeated_candidates:
            repeated_today_candidates.append((chapter, repeated_candidates))

    if not (primary_chapter_candidates or recent_chapter_candidates or repeated_today_candidates):
        return {
            "generated_at": today,
            "total": 0,
            "requested_count": count,
            "sampled_chapters": 0,
            "fresh_only": True,
            "items": [],
        }

    def extend_randomly(
        selected: list[tuple[dict[str, Any], list[tuple[float, dict[str, Any], dict[str, str]]]]],
        pool: list[tuple[dict[str, Any], list[tuple[float, dict[str, Any], dict[str, str]]]]],
        remaining: int,
    ) -> int:
        if remaining <= 0 or not pool:
            return remaining
        take = min(remaining, len(pool))
        selected.extend(rng.sample(pool, k=take))
        return remaining - take

    selected_chapters: list[tuple[dict[str, Any], list[tuple[float, dict[str, Any], dict[str, str]]]]] = []
    remaining = count
    remaining = extend_randomly(selected_chapters, primary_chapter_candidates, remaining)
    remaining = extend_randomly(selected_chapters, recent_chapter_candidates, remaining)
    extend_randomly(selected_chapters, repeated_today_candidates, remaining)
    sample_size = len(selected_chapters)

    picked: list[dict[str, Any]] = []
    for chapter, candidates in selected_chapters:
        topic = candidates[0][1]
        prompt_variant = candidates[0][2]
        picked.append(
            {
                "chapter_no": chapter["chapter_no"],
                "chapter_title": chapter["chapter_title"],
                "topic_id": topic["topic_id"],
                "heading": topic["heading"],
                "title": topic["title"],
                "importance": topic["importance"],
                "prompt_id": prompt_variant["prompt_id"],
                "question_prompt": prompt_variant["question_prompt"],
                "page": topic["page"],
                "end_page": topic["end_page"],
                "state": state["topics"][topic["topic_id"]],
            }
        )

    picked.sort(key=lambda item: item["chapter_no"])
    related_real_cases = attach_real_case_screenshots(vault, pick_related_real_cases(vault, picked, real_case_count), today)

    return {
        "generated_at": date.today().isoformat(),
        "total": len(picked),
        "requested_count": count,
        "sampled_chapters": sample_size,
        "fresh_only": len(primary_chapter_candidates) >= sample_size,
        "items": picked,
        "real_case_count": len(related_real_cases),
        "real_cases": related_real_cases,
    }


def format_pick_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# 案例冲刺题单（{payload['generated_at']}）",
        "",
        f"> 本轮共 {payload['total']} 道知识点题，随机抽取 {payload.get('sampled_chapters', payload['total'])} 个章节，每章 1 题，不重复",
        f"> 额外补充 {payload.get('real_case_count', 0)} 道最相关往年真题，用来把本轮知识点和真实案例题型连起来",
        "",
    ]
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    titles: dict[int, str] = {}
    for item in payload["items"]:
        grouped[item["chapter_no"]].append(item)
        titles[item["chapter_no"]] = item["chapter_title"]

    for chapter_no in sorted(grouped):
        lines.append(f"## 第 {chapter_no} 章：{titles[chapter_no]}")
        lines.append("")
        for idx, item in enumerate(grouped[chapter_no], start=1):
            prompt = item["question_prompt"].replace("\n", "\n     ")
            lines.append(
                f"{idx}. `{item['topic_id']}` / `{item['prompt_id']}` {item['heading']} {item['title']}  "
                f"\n   - 提问：{prompt}  "
                f"\n   - 教材页码：{item['page']}-{item['end_page']}"
            )
        lines.append("")

    if payload.get("real_cases"):
        lines.append("## 关联真题")
        lines.append("")
        for index, item in enumerate(payload["real_cases"], start=payload["total"] + 1):
            lines.append(f"{index}. `[真题]` `{item['real_question_id']}` {item['exam_label']} / {item['category']}")
            lines.append(f"   - 关联知识点：{('、'.join(item.get('matched_topics', [])) or '本轮综合知识点')}")
            lines.append(f"   - 材料页码：{item['start_page']}-{item['end_page']}")
            lines.append(f"   - 题干背景：{item['stem_excerpt'] or item['subject']}")
            for problem in item.get("problems", [])[:3]:
                lines.append(f"   - 问题（{problem['index']}）：{problem['prompt']}")
            for screenshot_path in item.get("screenshot_paths", []):
                page_no = Path(screenshot_path).stem.rsplit("-", 1)[-1]
                lines.append(f"   - 截图：![{item['real_question_id']} 第 {page_no} 页]({screenshot_path})")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def show_topic(vault: Path, topic_id: str) -> str:
    bank, _state = load_bank_and_state(vault)
    topic = next((item for item in all_topics(bank) if item["topic_id"] == topic_id), None)
    if topic is None:
        raise SystemExit(f"未找到 topic_id: {topic_id}")
    pdf_path = vault / PDF_RELATIVE_PATH
    extracted = run_pdftotext(pdf_path, topic["page"], topic["end_page"])
    cleaned = clean_extracted_text(extracted)
    header = [
        f"# {topic['heading']} {topic['title']}",
        "",
        f"- 章节：第 {topic['chapter_no']} 章 {topic['chapter_title']}",
        f"- 页码：{topic['page']}-{topic['end_page']}",
        "",
    ]
    return "\n".join(header) + cleaned + "\n"


def show_real_case(vault: Path, real_question_id: str) -> str:
    bank = load_real_case_bank(vault)
    item = next((row for row in bank.get("items", []) if row["real_question_id"] == real_question_id), None)
    if item is None:
        raise SystemExit(f"未找到 real_question_id: {real_question_id}")
    header = [
        f"# {item['exam_label']}",
        "",
        f"- 分类：{item['category']}",
        f"- 页码：{item['start_page']}-{item['end_page']}",
        f"- 主题：{item['subject']}",
        "",
    ]
    return "\n".join(header) + item["body_text"] + "\n"


def record_result(
    vault: Path,
    topic_id: str,
    result: str,
    today: str,
    user_answer: str,
    note: str,
    force_keep: bool,
    prompt_id: str = "",
    prompt_text: str = "",
) -> None:
    bank, state = load_bank_and_state(vault)
    if topic_id not in state["topics"]:
        raise SystemExit(f"未找到 topic_id: {topic_id}")
    entry = state["topics"][topic_id]
    first_time = entry["ask_count"] == 0
    entry["ask_count"] += 1
    entry["last_result"] = result
    entry["last_asked"] = today
    entry["last_prompt_id"] = prompt_id or entry.get("last_prompt_id")

    if result == "correct":
        entry["correct_count"] += 1
        if first_time:
            entry["first_attempt_correct"] = True
        if first_time and not force_keep:
            entry["mastery"] = max(entry["mastery"], 3)
            entry["status"] = "retired"
            entry["retired"] = True
        else:
            entry["mastery"] = max(entry["mastery"], 2)
            entry["status"] = "reviewing"
            entry["retired"] = False
    elif result == "partial":
        entry["partial_count"] += 1
        if first_time:
            entry["first_attempt_correct"] = False
        entry["mastery"] = max(entry["mastery"], 1)
        entry["status"] = "reviewing"
        entry["retired"] = False
    elif result == "wrong":
        entry["wrong_count"] += 1
        if first_time:
            entry["first_attempt_correct"] = False
        entry["mastery"] = 0
        entry["status"] = "reviewing"
        entry["retired"] = False
    else:
        raise SystemExit("result 只支持 correct / partial / wrong")

    if prompt_id:
        entry["question_history"].append(
            {
                "date": today,
                "prompt_id": prompt_id,
                "prompt_text": prompt_text,
            }
        )

    entry["history"].append(
        {
            "date": today,
            "result": result,
            "user_answer": user_answer,
            "note": note,
            "force_keep": force_keep,
            "prompt_id": prompt_id,
            "prompt_text": prompt_text,
        }
    )

    state["updated_at"] = today
    save_json(vault / STATE_PATH, state)
    (vault / REPORT_PATH).write_text(render_report(bank, state), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="系统架构设计师案例冲刺抽题工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh", help="刷新题库和掌握状态")
    refresh_parser.add_argument("--vault", required=True)

    pick_parser = subparsers.add_parser("pick", help="生成本轮题单")
    pick_parser.add_argument("--vault", required=True)
    pick_parser.add_argument("--seed", type=int)
    pick_parser.add_argument("--count", type=int, default=DEFAULT_PICK_COUNT)
    pick_parser.add_argument("--real-count", type=int, default=DEFAULT_REAL_CASE_COUNT)
    pick_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    show_parser = subparsers.add_parser("show", help="提取指定知识点的教材原文")
    show_parser.add_argument("--vault", required=True)
    show_parser.add_argument("--topic-id", required=True)

    show_real_parser = subparsers.add_parser("show-real", help="提取指定真题的原文")
    show_real_parser.add_argument("--vault", required=True)
    show_real_parser.add_argument("--real-question-id", required=True)

    record_parser = subparsers.add_parser("record", help="回写单个知识点作答结果")
    record_parser.add_argument("--vault", required=True)
    record_parser.add_argument("--topic-id", required=True)
    record_parser.add_argument("--result", required=True, choices=("correct", "partial", "wrong"))
    record_parser.add_argument("--today", default=date.today().isoformat())
    record_parser.add_argument("--user-answer", default="")
    record_parser.add_argument("--note", default="")
    record_parser.add_argument("--force-keep", action="store_true")
    record_parser.add_argument("--prompt-id", default="")
    record_parser.add_argument("--prompt-text", default="")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    vault = Path(args.vault).expanduser().resolve()

    if args.command == "refresh":
        refresh(vault)
        print(f"已刷新：{vault / BANK_PATH}")
        print(f"已刷新：{vault / REAL_CASE_BANK_PATH}")
        print(f"已刷新：{vault / STATE_PATH}")
        print(f"已刷新：{vault / REPORT_PATH}")
        return

    if args.command == "pick":
        payload = pick_topics(vault, args.seed, args.count, args.real_count)
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(format_pick_markdown(payload))
        return

    if args.command == "show":
        print(show_topic(vault, args.topic_id))
        return

    if args.command == "show-real":
        print(show_real_case(vault, args.real_question_id))
        return

    if args.command == "record":
        record_result(
            vault=vault,
            topic_id=args.topic_id,
            result=args.result,
            today=args.today,
            user_answer=args.user_answer,
            note=args.note,
            force_keep=args.force_keep,
            prompt_id=args.prompt_id,
            prompt_text=args.prompt_text,
        )
        print(f"已记录：{args.topic_id} -> {args.result}")
        return


if __name__ == "__main__":
    main()
