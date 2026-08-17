# 场景：全流程AI Agent自动化开发产品

> 人当做PCM系统，去调度AI Agent自动化工作流（claude code cli）详细全流程步骤。
> 每一步必须完成目标，不完成目标不可以进入下一步。
> 有些步骤是需要新开AI Agent会话的，这些步骤每一个都是在单独的会话窗口。换句话说，就是一个步骤内的所有操作，都会在一个会话窗口内共享上下文。避免上下文污染，合理的成本控制。
> 本文所写的是一个默认标椎模板流程（步骤设计）。目前PCM系统会把这个作为第一个模板流程，之后的话会拓展更多的可选模板流程的。当前的AI Agent的构建的执行语义就是为了解耦，方便以后可以组成不同的流程。你知道的，对于人来说，这种灵活性是可以随意组合的。但是对于程序来说，为了保证整个链路上下节点能够承接，就必须把它们做成一个个固定的流程模板。
> 本流程设计专做web应用开发，前后端分离设计。


第1步：获取产品初稿，使用 `pcm-product-factory` skill。默认使用3选1模式。（这个skill可以在任何地方使用，其实严格地来说，它并不算是这个AI Agent自动化开发流程一个skill。主要就是为了提供一个项目产品初稿）
输出：初版产品文档。
目标：需要进行多次对话和决策，直到完成输出文档的编写。


第2步：操作。`git clone git@gitlab.com:baiyiyu/andrszan/pcm-agent-skills.git <指定的的选题项目名文件夹路径>` 拉取AI Agent skill这个git项目到开发环境（指定路径），作为选题项目文件夹的顶层的“AI Agent自动化开发管理项目”。还需要一些初始化操作处理：删掉 .git 文件夹和 /docs 文件夹。前者会在后面的流程做新的项目git初始化操作，后者会放当前选题项目的相关文档。
从这步开始，之后所有操作都会在这个新的项目根目录下进行，AI Agent的自动化开发流程正式开始。
输入：选题名
目标：完成开发文件夹的搭建。


第3步：项目需求分析，使用 `project-intake` skill。
输入：第1步的产出文档（路径）。[`初版产品文档`]
输出：项目需求文档和产品功能文档。
目标：需要进行多次对话和决策，直到完成输出文档的编写。


第4步：技术方案，使用 `solution-design` skill。
输入：
- 第2步的产出文档（路径）。[`项目需求文档`,`产品功能文档`]
- 模板仓库的 repositories.yaml、templates.yaml 和契约/说明文档文档（这些文件来源于基础模板仓库管理项目：git@gitlab.com:baiyiyu/andrszan/pcm-repository/pcm-template-projects.git）
输出：
- 技术方案文档
- 模板仓库前端/后端基础项目选型组合结果。
目标：需要进行多次对话和决策，直到完成输出文档的编写和获取选型组合结果。（人的话，是会直接从字面意思理解是哪些个项目，然后去操作。但是如果是PCM系统程序设计的话，就需要一个方案了，最终要的是固定的json格式数据）


第5步：操作。去拉取模板仓库的git项目，然后获取到对应的前后端仓库的基础选型项目文件夹，复制为当前项目的 frontend 和 backend 文件夹。示例(前端仓库 + python后端仓库)：
```bash
# 删除根目录下已有的frontend，backend文件夹（里面都只有 .gitkeep 一个文件）
rm -rf ./frontend ./backend
# 获取前端基础项目
git clone git@gitlab.com:baiyiyu/andrszan/pcm-repository/pcm-frontend-templates.git
cp ./pcm-frontend-templates/templates/vite-react-shadcn-spa ./frontend
# 获取python后端基础项目
git clone git@gitlab.com:baiyiyu/andrszan/pcm-repository/pcm-python-templates.git
cp ./pcm-python-templates/templates/fastapi-sqlalchemy-postgresql-api ./backend
# 复制完了就删除掉这两个模板git仓库
rm -rf ./pcm-frontend-templates ./pcm-python-templates
```
输入：第4步的 “模板仓库前端/后端基础项目选型组合结果”。
输出：项目文件夹
目标：完成项目文件夹的组装。


第6步：开发前需要的资源清单，使用 `project-readiness` skill。生成初版项目准备清单文档后，还不够，需要持续对话。需要确认所有清单都已准备就绪之后，才算完成这一步。如果需要的资源清单里面，在提供的资源列表中无论如何都无法满足，那就算为阻塞，需要开发者准备好了才行，或者需要开发者决策替换方案。
输入：
- 第3，4步的产出文档（路径）[`项目需求文档`,`产品功能文档`,`技术方案文档`]
- 根目录下的 @frontend/README.md @backend/README.md 
- 可用资源列表信息（都是真实值，允许开发环境使用的），比如数据库连接信息、第三方资源秘钥/api-key、......等等。（来源于开发者准备最新内容，之后由PCM系统管理）
输出：项目准备清单文档。
目标：需要进行多次对话和决策，直到完成输出文档的编写。


第7步：
<1>. 将当前模板内容进行项目化。执行 `project-bootstrap` skill。
输入：
- 第3，4，6步的产出文档（路径）[`项目需求文档`,`产品功能文档`,`技术方案文档`,`项目准备清单文档`]
- 根目录下的 @frontend @backend
输出：项目化后的项目文件夹，使用git初始化。
目标：需要进行多次对话和决策，直到完成代码和文档的编写，还有初始化3个仓库，分别第一次提交所有内容。注意，AI agent（Claude code）可能会阶段性地完成部分任务并停下向你汇报情况。你需要和他对话，让他继续完成所有任务。总之最终你需要确保所有工作完成，包括测试和验证性的工作。
<2>. 操作。将项目文件夹git初始化。分别在`顶层根目录下`、`./frontend前端`和`./backend后端` 目录下，执行 git 仓库初始化命令，进行git版本管理。主分支为main。
输入：无
输出：.git 文件夹
目标：git管理3个仓库
<3>. git提交变更内容。执行 `commit-changes` skill。初次提交所有项目内容，3个仓库分别提交各自git管理的内容。除了3个仓库的`.gitignore`文件里面的内容之外，其他所有的东西都是能够正常提交的（比如 .agent, .claude），这是设计好了的，所以正常全提交就行。
输入：无
输出：无
目标：本地提交所有内容。


第8步：
<1>. 前后端架构设计文档。执行 `engineering-architecture` skill。
还需要设计出前端和后端各自的架构，我说的是那种目录结构架构，然后出一份前后端各自的开发约定规范。
输入：
- 第3，4，6步的产出文档（路径）[`项目需求文档`,`产品功能文档`,`技术方案文档`,`项目准备清单文档`]
- 根目录下的 @frontend/README.md @backend/README.md 
输出：工程架构设计文档。
目标：需要进行多次对话和决策，直到完成输出文档的编写。
<2>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交 `工程架构设计文档`。


第9步：
<1>. 产品级 UI/UX 框架。执行 `ui-ux-framework bootstrap` skill。
输入：
- 第3，4，6，8步的产出文档（路径）[`项目需求文档`,`产品功能文档`,`技术方案文档`,`项目准备清单文档`，`工程架构设计文档`]
- 根目录下的 @frontend/README.md @backend/README.md 
输出：framework文档。
目标：需要进行多次对话和决策，直到完成输出文档的编写。
<2>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交 `framework文档`。


第10步：
<1>. 拆分大需求。执行 `requirement-breakdown` skill。
输入：
- 第3，4，6，8，9步的产出文档（路径）[`项目需求文档`,`产品功能文档`,`技术方案文档`,`项目准备清单文档`，`工程架构设计文档`,`framework文档`]
- 根目录下的 @frontend/README.md @backend/README.md 
输出：backlog文档。
目标：需要进行多次对话和决策，直到完成输出文档的编写。
<2>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交 `backlog文档`。


>>> 开始循环执行 <<<

第11步：
<1>. 详细设计需求。使用 `/trd-design` skill, 根据backog文档，按顺序将一个大需求整理为TRD文档。
输入：
- 第10步的产出文档（路径）[`backlog文档`]
输出：xxx-TRD文档。
目标：需要进行多次对话和决策，直到完成输出文档的编写。
<2>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交 `xxx-TRD文档`。


第12步：
<1>. 开发前适用性判断与需求级设计。执行 `ui-ux-framework before` skill。
输入：第11步的产出文档（路径）[`xxx-TRD文档`]
输出：xxx-TRD文档。（会判断是否更新添加UI设计方面的内容）
目标：需要进行多次对话和决策，直到完成输出文档的编写。
<2>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交 `xxx-TRD文档`。


第13步：开始开发。
<1>. 需求开发。使用 `dev-workflow` skill，根据得到的TRD文档，开始正式的实现代码。要注意实现完代码之后需要检查分支情况，它有可能会新建分支，然后没有合并，还要注意修改需求完成的情况
输入：第12步的产出文档（路径）[`xxx-TRD文档`]
目标：需要进行多次对话和决策，直到完成代码的编写，注意，AI agent（Claude code）可能会阶段性地完成部分任务并停下向你汇报情况。你需要和他对话，让他继续完成所有任务。总之最终你需要确保所有工作完成，包括测试和验证性的工作。
当完成开发之后，如果Ai Agent新开了分支的话，需要把功能分支合并到main上去，你需要确保这个工作要完成，如果你明没有明确获取到这个合并到main的回复，你需要和他对话去确认一下。
开发过程中可能会产生一些副产物，比如./claude/worktree，同样的，需要确保AI Agent清除了它们。
<2>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交开发内容。需要确保修改的内容已提交到main分支。
<3>. 从执行问题中沉淀可复用规则。使用 `session-rule-retrospective 本次会话` skill，沉淀本次会话开发中遇到的问题，这些问题是后续很可能会再次遇到的。
输出：.claude/rules/xxx文档。（如果有发现可以沉淀的内容，会新增或修改rules文档）
目标：需要进行多次对话和决策，直到完成输出文档的编写（如果有需要沉淀的内容）。
<4>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交沉淀规则。


第14步：
<1>. 开发后适用性判断与体验审查。执行 `ui-ux-framework after` skill。
输入：第11步的产出文档（路径）[`xxx-TRD文档`]
目标：如果AI agent回复，表示发现了需要调整优化的前端设计，允许执行下一步，进入开发完善设计。最终你需要确保它把所有工作完成，包括测试和验证性的工作。需要确保修改的内容已提交到main分支。
<2>. git提交变更内容。执行 `commit-changes` skill。
输入：无
输出：无
目标：git提交开发内容。需要确保修改的内容已提交到main分支

>>> 结束循环执行 <<<
