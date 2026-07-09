# BDD AI Toolkit — VS Code 扩展详解

## 文件概览

BDD AI Toolkit 是一个 VS Code 扩展，提供 AI 辅助的 BDD（行为驱动开发）测试工作流。它包含约 50+ 个 TypeScript 源文件。

### 目录结构

```
bdd_ai_toolkit/
├── package.json                     # VS Code 扩展配置
├── tsconfig.json                    # TypeScript 配置
├── src/
│   ├── extension.ts                 # 扩展入口 (activate/deactivate)
│   ├── globalState.ts               # 全局状态管理
│   ├── constants/
│   │   └── prompts.ts               # LLM 提示词模板
│   ├── tools/                       # 工具模块
│   │   ├── index.ts                 # 工具导出
│   │   ├── interfaces.ts            # 工具接口定义
│   │   ├── testCaseGenerator.ts     # 测试用例生成器
│   │   ├── naturalLanguageTaskExecutor.ts  # 自然语言任务执行
│   │   ├── testCaseWorkflowPatterns.ts     # 工作流模式
│   │   ├── figmaExtractor.ts        # Figma 设计提取
│   │   └── xmindParser.ts           # XMind 思维导图解析
│   ├── bdd-feature-support/         # BDD Feature 核心支持
│   │   ├── index.ts                 # 模块入口
│   │   ├── extension.ts             # Feature 支持激活
│   │   ├── core/                    # 核心引擎
│   │   │   ├── index.ts
│   │   │   ├── gherkin/             # Gherkin 语法解析
│   │   │   │   ├── index.ts
│   │   │   │   ├── types.ts         # Gherkin AST 类型
│   │   │   │   ├── FeatureParser.ts       # Feature 文件解析器
│   │   │   │   ├── ScenarioExtractor.ts   # Scenario 提取器
│   │   │   │   ├── StepExtractor.ts       # Step 提取器
│   │   │   │   └── BackgroundExtractor.ts # Background 提取器
│   │   │   └── matching/            # Step 匹配引擎
│   │   │       ├── index.ts
│   │   │       ├── types.ts         # 匹配相关类型
│   │   │       ├── StepMatcher.ts         # Step 匹配器
│   │   │       ├── StepDefinitionLoader.ts # Step 定义加载器
│   │   │       └── PatternConverter.ts    # 模式转换器
│   │   ├── providers/               # VS Code UI Provider
│   │   │   ├── index.ts
│   │   │   ├── CodeLensProvider.ts        # 代码透镜
│   │   │   ├── DecorationProvider.ts      # 装饰器
│   │   │   └── WebviewProvider.ts         # Webview 面板
│   │   ├── services/                # 业务服务
│   │   │   ├── index.ts
│   │   │   ├── AutomationStatusService.ts # 自动化状态服务
│   │   │   ├── CopilotIntegrationService.ts # Copilot 集成
│   │   │   ├── DryRunService.ts           # 干运行服务
│   │   │   └── FileWatcherManager.ts      # 文件监听
│   │   ├── cache/                   # 缓存管理
│   │   │   ├── index.ts
│   │   │   ├── UnifiedCacheManager.ts     # 统一缓存管理
│   │   │   ├── AutomationStatusCache.ts   # 自动化状态缓存
│   │   │   ├── PythonFileCache.ts         # Python 文件缓存
│   │   │   └── StepMatchCache.ts          # Step 匹配缓存
│   │   └── utils/                   # 工具函数
│   │       ├── index.ts
│   │       ├── ConfigManager.ts           # 配置管理
│   │       ├── PathResolver.ts            # 路径解析
│   │       ├── FileWatcher.ts             # 文件监听器
│   │       ├── CommandHandlers.ts         # 命令处理器
│   │       └── HtmlTemplateManager.ts     # HTML 模板
│   └── setup/                       # 环境安装向导
│       ├── index.ts
│       ├── environment.ts           # 环境检测
│       ├── platform.ts              # 平台检测
│       ├── python.ts                # Python 环境管理
│       ├── fileSystem.ts            # 文件系统操作
│       ├── mcpServerManager.ts      # MCP 服务器管理
│       ├── setupUtils.ts            # 安装工具
│       ├── SetupWebViewProvider.ts  # 安装向导 UI
│       ├── terminal.ts              # 终端管理
│       ├── uv.ts                    # UV 包管理器
│       ├── versionManager.ts        # 版本管理
│       └── webview.ts               # Webview 工具
└── resources/                       # 静态资源
    ├── main.ts                      # Webview 主脚本
    ├── webview.html                 # Webview HTML
    ├── automation-details.html      # 自动化详情面板
    └── styles.css                   # 样式
```

---

## 一、扩展入口（`src/extension.ts`）

### 1.1 概述

```typescript
// 位置: bdd_ai_toolkit/src/extension.ts

import * as vscode from 'vscode';
import { activateFeatureSupport } from './bdd-feature-support';
import { activateSetup } from './setup';

export function activate(context: vscode.ExtensionContext) {
    console.log('BDD AI Toolkit is now active!');
    
    // 初始化全局状态
    GlobalState.init(context);
    
    // 激活 BDD Feature 支持（核心功能）
    activateFeatureSupport(context);
    
    // 激活环境安装向导
    activateSetup(context);
    
    // 注册命令
    registerCommands(context);
}

export function deactivate() {
    // 清理资源
}
```

### 1.2 命令注册

```typescript
// 位置: bdd_ai_toolkit/src/extension.ts

function registerCommands(context: vscode.ExtensionContext) {
    // 测试用例生成
    context.subscriptions.push(
        vscode.commands.registerCommand('bdd-ai-toolkit.generateTestCase', async () => {
            const generator = new TestCaseGenerator();
            await generator.generate();
        })
    );
    
    // 自然语言任务执行
    context.subscriptions.push(
        vscode.commands.registerCommand('bdd-ai-toolkit.executeNaturalLanguageTask', async () => {
            const executor = new NaturalLanguageTaskExecutor();
            await executor.execute();
        })
    );
    
    // 从 Figma 生成测试
    context.subscriptions.push(
        vscode.commands.registerCommand('bdd-ai-toolkit.generateFromFigma', async () => {
            const extractor = new FigmaExtractor();
            await extractor.extract();
        })
    );
    
    // 从 XMind 生成测试
    context.subscriptions.push(
        vscode.commands.registerCommand('bdd-ai-toolkit.generateFromXMind', async () => {
            const parser = new XmindParser();
            await parser.parse();
        })
    );
    
    // 打开安装向导
    context.subscriptions.push(
        vscode.commands.registerCommand('bdd-ai-toolkit.openSetupWizard', () => {
            SetupWebViewProvider.createOrShow(context);
        })
    );
}
```

---

## 二、全局状态管理（`src/globalState.ts`）

```typescript
// 位置: bdd_ai_toolkit/src/globalState.ts

export class GlobalState {
    private static context: vscode.ExtensionContext;
    
    static init(context: vscode.ExtensionContext) {
        this.context = context;
    }
    
    // 持久化状态存储
    static get<T>(key: string, defaultValue?: T): T {
        return this.context.globalState.get<T>(key) ?? defaultValue;
    }
    
    static set(key: string, value: any): Thenable<void> {
        return this.context.globalState.update(key, value);
    }
    
    // 工作区状态存储
    static getWorkspace<T>(key: string, defaultValue?: T): T {
        return this.context.workspaceState.get<T>(key) ?? defaultValue;
    }
    
    static setWorkspace(key: string, value: any): Thenable<void> {
        return this.context.workspaceState.update(key, value);
    }
}
```

---

## 三、工具模块（`src/tools/`）

### 3.1 接口定义（`interfaces.ts`）

```typescript
// 位置: bdd_ai_toolkit/src/tools/interfaces.ts

export interface TestCase {
    name: string;
    description: string;
    steps: TestStep[];
    preconditions: string[];
    expectedResults: string[];
    tags: string[];
}

export interface TestStep {
    type: 'Given' | 'When' | 'Then' | 'And' | 'But';
    description: string;
    data?: Record<string, any>;
}

export interface Feature {
    name: string;
    description: string;
    scenarios: Scenario[];
    background?: Background;
    tags: string[];
}

export interface Scenario {
    name: string;
    type: 'Scenario' | 'Scenario Outline';
    steps: TestStep[];
    examples?: ExampleTable;
    tags: string[];
}

export interface ExampleTable {
    headers: string[];
    rows: Record<string, string>[];
}

export interface WorkflowPattern {
    name: string;
    description: string;
    steps: TestStep[];
    applicableTags: string[];
}
```

### 3.2 `testCaseGenerator.ts` — 测试用例生成器

```typescript
// 位置: bdd_ai_toolkit/src/tools/testCaseGenerator.ts

export class TestCaseGenerator {
    /**
     * 核心功能: 从多种输入源生成 BDD 测试用例
     * 
     * 输入源:
     * 1. 当前打开的 .feature 文件
     * 2. 用户选中的文本
     * 3. 自然语言描述
     * 4. Figma 设计稿
     * 5. XMind 思维导图
     * 
     * 输出: 结构化的 Gherkin Feature 文件
     */
    
    async generate(): Promise<void> {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;
        
        // 获取上下文
        const selection = editor.selection;
        const selectedText = editor.document.getText(selection);
        const fullText = editor.document.getText();
        
        // 调用 LLM 生成测试用例
        const prompt = this._buildPrompt(selectedText || fullText);
        const generatedCode = await this._callLLM(prompt);
        
        // 解析并插入生成的测试用例
        const testCases = this._parseGherkin(generatedCode);
        await this._insertTestCases(editor, testCases);
    }
    
    private _buildPrompt(context: string): string {
        return `
${SYSTEM_PROMPT}

## Context
${context}

## Task
Generate comprehensive BDD test scenarios in Gherkin format.
Include:
- Feature description
- Multiple scenarios covering happy path, edge cases, and error cases
- Scenario Outlines with Examples for data-driven tests
- Proper tags for organization
        `;
    }
    
    private async _callLLM(prompt: string): Promise<string> {
        // 通过 Copilot MCP 或直接 API 调用 LLM
        // ...
    }
}
```

### 3.3 `naturalLanguageTaskExecutor.ts` — 自然语言任务执行

```typescript
// 位置: bdd_ai_toolkit/src/tools/naturalLanguageTaskExecutor.ts

export class NaturalLanguageTaskExecutor {
    /**
     * 将自然语言描述转换为可执行的 MCP 工具调用。
     * 
     * 工作流:
     * 1. 用户输入自然语言任务描述
     * 2. LLM 解析意图 → 生成工具调用序列
     * 3. 通过 MCP 协议发送到 MCP Server
     * 4. 执行 UI 操作
     * 5. 返回操作结果
     */
    
    async execute(): Promise<void> {
        // 获取用户输入
        const taskDescription = await vscode.window.showInputBox({
            prompt: 'Describe the test task in natural language',
            placeHolder: 'e.g., "Open the app, login with admin/admin, and verify the dashboard shows 5 widgets"'
        });
        
        if (!taskDescription) return;
        
        // 获取可用的 MCP 工具列表
        const tools = await this._getAvailableTools();
        
        // 让 LLM 规划执行步骤
        const plan = await this._planExecution(taskDescription, tools);
        
        // 逐步执行
        for (const step of plan.steps) {
            await this._executeStep(step);
        }
        
        // 生成测试代码
        await this._generateTestCode(plan);
    }
    
    private async _planExecution(task: string, tools: any[]): Promise<ExecutionPlan> {
        const prompt = `
You are a test automation planner. Given the following task and available tools,
create a step-by-step execution plan.

## Task
${task}

## Available Tools
${JSON.stringify(tools, null, 2)}

## Output Format
{
  "steps": [
    { "tool": "tool_name", "params": {...}, "description": "..." }
  ]
}
        `;
        // 调用 LLM...
    }
}
```

### 3.4 `testCaseWorkflowPatterns.ts` — 工作流模式

```typescript
// 位置: bdd_ai_toolkit/src/tools/testCaseWorkflowPatterns.ts

export class TestCaseWorkflowPatterns {
    /**
     * 预定义的测试工作流模式库。
     * 提供常见的测试模式模板，加速测试用例编写。
     */
    
    static readonly PATTERNS: WorkflowPattern[] = [
        {
            name: 'Login Flow',
            description: 'User authentication workflow',
            steps: [
                { type: 'Given', description: 'the user is on the login page' },
                { type: 'When', description: 'the user enters valid credentials' },
                { type: 'And', description: 'clicks the login button' },
                { type: 'Then', description: 'the user should be redirected to the dashboard' },
            ],
            applicableTags: ['@login', '@authentication', '@smoke'],
        },
        {
            name: 'Form Validation',
            description: 'Form input validation workflow',
            steps: [
                { type: 'Given', description: 'the user is on the form page' },
                { type: 'When', description: 'the user submits an empty form' },
                { type: 'Then', description: 'validation error messages should be displayed' },
            ],
            applicableTags: ['@validation', '@form', '@regression'],
        },
        {
            name: 'CRUD Operations',
            description: 'Create, Read, Update, Delete workflow',
            steps: [
                { type: 'Given', description: 'the user is authenticated' },
                { type: 'When', description: 'the user creates a new item' },
                { type: 'Then', description: 'the item should appear in the list' },
                { type: 'When', description: 'the user updates the item' },
                { type: 'Then', description: 'the changes should be reflected' },
                { type: 'When', description: 'the user deletes the item' },
                { type: 'Then', description: 'the item should no longer appear' },
            ],
            applicableTags: ['@crud', '@integration'],
        },
    ];
    
    /**
     * 根据标签匹配适用的模式
     */
    static findPatternsByTags(tags: string[]): WorkflowPattern[] {
        return this.PATTERNS.filter(pattern =>
            pattern.applicableTags.some(tag => tags.includes(tag))
        );
    }
}
```

### 3.5 `figmaExtractor.ts` — Figma 设计提取

```typescript
// 位置: bdd_ai_toolkit/src/tools/figmaExtractor.ts

export class FigmaExtractor {
    /**
     * 从 Figma 设计稿中提取 UI 信息并生成测试用例。
     * 
     * 输入: Figma 文件 URL 或 JSON 导出
     * 输出: 
     *   1. UI 元素列表（名称、类型、层级）
     *   2. 交互流程描述
     *   3. 自动生成的 Gherkin 测试用例
     */
    
    async extract(): Promise<void> {
        const figmaUrl = await vscode.window.showInputBox({
            prompt: 'Enter Figma file URL or select a JSON export file'
        });
        
        if (!figmaUrl) return;
        
        // 解析 Figma 设计
        const designData = await this._parseFigma(figmaUrl);
        
        // 提取 UI 元素和交互
        const elements = this._extractElements(designData);
        const flows = this._extractFlows(designData);
        
        // 生成 Gherkin 测试用例
        const testCases = await this._generateGherkin(elements, flows);
        
        // 插入到当前编辑器
        await this._insertIntoEditor(testCases);
    }
}
```

### 3.6 `xmindParser.ts` — XMind 解析器

```typescript
// 位置: bdd_ai_toolkit/src/tools/xmindParser.ts

export class XmindParser {
    /**
     * 解析 XMind 思维导图文件，提取测试场景结构。
     * 
     * XMind 节点层级 → Gherkin 结构映射:
     * 
     * 根节点        → Feature
     *   ├── 子节点1  → Scenario
     *   │   ├── Given → Given step
     *   │   ├── When  → When step
     *   │   └── Then  → Then step
     *   └── 子节点2  → Scenario Outline
     *       └── ...
     */
    
    async parse(): Promise<void> {
        const fileUri = await vscode.window.showOpenDialog({
            filters: { 'XMind Files': ['xmind'] }
        });
        
        if (!fileUri) return;
        
        // 读取 XMind 文件
        const xmindData = await this._readXmindFile(fileUri[0]);
        
        // 转换为 Feature 结构
        const feature = this._convertToFeature(xmindData);
        
        // 生成 Gherkin 文本
        const gherkinText = this._toGherkin(feature);
        
        // 写入 .feature 文件
        await this._writeFeatureFile(gherkinText);
    }
    
    private _convertToFeature(xmindData: any): Feature {
        const root = xmindData.rootTopic;
        const feature: Feature = {
            name: root.title,
            description: '',
            scenarios: [],
            tags: [],
        };
        
        for (const child of root.children?.attached || []) {
            feature.scenarios.push(this._nodeToScenario(child));
        }
        
        return feature;
    }
}
```

---

## 四、Gherkin 解析引擎（`bdd-feature-support/core/gherkin/`）

### 4.1 类型定义（`types.ts`）

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/core/gherkin/types.ts

export interface GherkinDocument {
    feature: GherkinFeature;
    comments: GherkinComment[];
}

export interface GherkinFeature {
    name: string;
    description: string;
    tags: GherkinTag[];
    background?: GherkinBackground;
    scenarios: GherkinScenario[];
    location: SourceLocation;
}

export interface GherkinScenario {
    name: string;
    type: 'Scenario' | 'ScenarioOutline';
    steps: GherkinStep[];
    tags: GherkinTag[];
    examples?: GherkinExamples;
    location: SourceLocation;
}

export interface GherkinStep {
    keyword: 'Given' | 'When' | 'Then' | 'And' | 'But';
    text: string;
    argument?: GherkinDataTable | GherkinDocString;
    location: SourceLocation;
}

export interface GherkinBackground {
    name: string;
    steps: GherkinStep[];
    location: SourceLocation;
}

export interface GherkinExamples {
    name: string;
    header: string[];
    rows: string[][];
    location: SourceLocation;
}

export interface SourceLocation {
    line: number;
    column: number;
}
```

### 4.2 FeatureParser — Feature 文件解析器

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/core/gherkin/FeatureParser.ts

export class FeatureParser {
    /**
     * 解析 .feature 文件为结构化数据。
     * 使用正则表达式进行轻量级解析（不依赖官方 Gherkin 解析器）。
     */
    
    parse(content: string, filePath: string): GherkinDocument {
        const lines = content.split('\n');
        const document: GherkinDocument = {
            feature: null,
            comments: [],
        };
        
        let currentFeature: GherkinFeature = null;
        let currentScenario: GherkinScenario = null;
        let currentBackground: GherkinBackground = null;
        let inExamples = false;
        let currentExamples: GherkinExamples = null;
        
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            const lineNumber = i + 1;
            
            // 跳过空行和注释
            if (!line || line.startsWith('#')) {
                if (line.startsWith('#')) {
                    document.comments.push({ text: line.substring(1).trim(), location: { line: lineNumber, column: 1 } });
                }
                continue;
            }
            
            // Feature
            if (line.startsWith('Feature:')) {
                currentFeature = {
                    name: line.substring('Feature:'.length).trim(),
                    description: '',
                    tags: [],
                    scenarios: [],
                    location: { line: lineNumber, column: 1 },
                };
                document.feature = currentFeature;
                continue;
            }
            
            // Background
            if (line.startsWith('Background:')) {
                currentBackground = {
                    name: line.substring('Background:'.length).trim(),
                    steps: [],
                    location: { line: lineNumber, column: 1 },
                };
                currentFeature.background = currentBackground;
                continue;
            }
            
            // Scenario / Scenario Outline
            if (line.startsWith('Scenario:') || line.startsWith('Scenario Outline:') || 
                line.startsWith('Example:') || line.startsWith('Scenario Template:')) {
                const isOutline = line.startsWith('Scenario Outline:') || line.startsWith('Scenario Template:');
                currentScenario = {
                    name: line.substring(line.indexOf(':') + 1).trim(),
                    type: isOutline ? 'ScenarioOutline' : 'Scenario',
                    steps: [],
                    tags: [],
                    location: { line: lineNumber, column: 1 },
                };
                currentFeature.scenarios.push(currentScenario);
                inExamples = false;
                continue;
            }
            
            // Examples
            if (line.startsWith('Examples:')) {
                inExamples = true;
                currentExamples = {
                    name: line.substring('Examples:'.length).trim(),
                    header: [],
                    rows: [],
                    location: { line: lineNumber, column: 1 },
                };
                continue;
            }
            
            // Tags
            if (line.startsWith('@')) {
                const tags = line.split(/\s+/).filter(t => t.startsWith('@'));
                if (currentScenario) {
                    currentScenario.tags.push(...tags);
                } else if (currentFeature) {
                    currentFeature.tags.push(...tags);
                }
                continue;
            }
            
            // Steps
            const stepMatch = line.match(/^(Given|When|Then|And|But)\s+(.+)/i);
            if (stepMatch) {
                const step: GherkinStep = {
                    keyword: stepMatch[1] as any,
                    text: stepMatch[2],
                    location: { line: lineNumber, column: 1 },
                };
                
                if (currentBackground && !currentScenario) {
                    currentBackground.steps.push(step);
                } else if (currentScenario && !inExamples) {
                    currentScenario.steps.push(step);
                }
                continue;
            }
            
            // Examples table rows
            if (inExamples && line.startsWith('|')) {
                const cells = line.split('|').map(c => c.trim()).filter(Boolean);
                if (currentExamples.header.length === 0) {
                    currentExamples.header = cells;
                } else {
                    currentExamples.rows.push(cells);
                }
                continue;
            }
            
            // Description text (anything else)
            if (currentFeature && !currentScenario) {
                currentFeature.description += line + '\n';
            }
        }
        
        return document;
    }
}
```

### 4.3 StepExtractor — Step 提取器

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/core/gherkin/StepExtractor.ts

export class StepExtractor {
    /**
     * 从 GherkinDocument 中提取所有 Step。
     * 返回扁平化的步骤列表，包含来源信息。
     */
    
    extractAllSteps(document: GherkinDocument): ExtractedStep[] {
        const steps: ExtractedStep[] = [];
        
        // 提取 Background steps
        if (document.feature.background) {
            for (const step of document.feature.background.steps) {
                steps.push({
                    ...step,
                    source: 'background',
                    scenarioName: document.feature.background.name,
                });
            }
        }
        
        // 提取所有 Scenario steps
        for (const scenario of document.feature.scenarios) {
            for (const step of scenario.steps) {
                steps.push({
                    ...step,
                    source: scenario.type,
                    scenarioName: scenario.name,
                    tags: scenario.tags,
                });
            }
        }
        
        return steps;
    }
}

export interface ExtractedStep extends GherkinStep {
    source: 'background' | 'Scenario' | 'ScenarioOutline';
    scenarioName: string;
    tags?: string[];
}
```

---

## 五、Step 匹配引擎（`bdd-feature-support/core/matching/`）

### 5.1 类型定义（`types.ts`）

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/core/matching/types.ts

export interface StepDefinition {
    type: 'Given' | 'When' | 'Then';
    pattern: string;            // 正则表达式模式字符串
    regex: RegExp;              // 编译后的正则
    functionName: string;       // Python 函数名
    filePath: string;           // 所在文件路径
    lineNumber: number;         // 行号
    parameters: string[];       // 参数名列表
}

export interface StepMatch {
    step: GherkinStep;          // Gherkin Step
    definition: StepDefinition; // 匹配的 Step Definition
    score: number;              // 匹配置信度 (0-1)
    parameters: Record<string, string>; // 提取的参数值
}

export interface MatchResult {
    matches: StepMatch[];       // 成功匹配
    unmatched: GherkinStep[];   // 未匹配的 Step
    ambiguous: StepMatch[][];   // 多个匹配的 Step
}
```

### 5.2 StepMatcher — 核心匹配器

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/core/matching/StepMatcher.ts

export class StepMatcher {
    /**
     * 将 Gherkin Step 文本与 Python Step Definition 进行匹配。
     * 
     * 匹配策略:
     * 1. 精确文本匹配（最高优先级）
     * 2. 正则表达式匹配
     * 3. 模糊匹配（编辑距离）
     * 4. AI 辅助匹配（调用 LLM）
     */
    
    private definitions: StepDefinition[] = [];
    private llmMatcher: LLMStepMatcher;
    
    match(steps: GherkinStep[]): MatchResult {
        const result: MatchResult = {
            matches: [],
            unmatched: [],
            ambiguous: [],
        };
        
        for (const step of steps) {
            const candidates = this._findCandidates(step);
            
            if (candidates.length === 0) {
                // 尝试 AI 匹配
                const aiMatch = this.llmMatcher.match(step, this.definitions);
                if (aiMatch) {
                    result.matches.push(aiMatch);
                } else {
                    result.unmatched.push(step);
                }
            } else if (candidates.length === 1) {
                result.matches.push(candidates[0]);
            } else {
                result.ambiguous.push(candidates);
            }
        }
        
        return result;
    }
    
    private _findCandidates(step: GherkinStep): StepMatch[] {
        const matches: StepMatch[] = [];
        
        for (const def of this.definitions) {
            // 只匹配同类型 (Given→Given, When→When, Then→Then)
            if (def.type.toLowerCase() !== step.keyword.toLowerCase()) {
                continue;
            }
            
            const match = step.text.match(def.regex);
            if (match) {
                matches.push({
                    step,
                    definition: def,
                    score: 1.0,
                    parameters: this._extractParameters(def.parameters, match),
                });
            }
        }
        
        return matches;
    }
    
    private _extractParameters(paramNames: string[], match: RegExpMatchArray): Record<string, string> {
        const params: Record<string, string> = {};
        // match[0] 是完整匹配，match[1] 开始是捕获组
        for (let i = 0; i < paramNames.length; i++) {
            params[paramNames[i]] = match[i + 1] || '';
        }
        return params;
    }
}
```

### 5.3 StepDefinitionLoader — Step 定义加载器

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/core/matching/StepDefinitionLoader.ts

export class StepDefinitionLoader {
    /**
     * 从 Python 文件中加载 Step Definition。
     * 解析 @given, @when, @then 装饰器。
     */
    
    async loadFromFile(filePath: string): Promise<StepDefinition[]> {
        const content = await this._readFile(filePath);
        return this._parseDefinitions(content, filePath);
    }
    
    async loadFromDirectory(dirPath: string): Promise<StepDefinition[]> {
        const pythonFiles = await this._findPythonFiles(dirPath);
        const allDefinitions: StepDefinition[] = [];
        
        for (const file of pythonFiles) {
            const defs = await this.loadFromFile(file);
            allDefinitions.push(...defs);
        }
        
        return allDefinitions;
    }
    
    private _parseDefinitions(content: string, filePath: string): StepDefinition[] {
        const definitions: StepDefinition[] = [];
        const lines = content.split('\n');
        
        // 正则匹配 Behave 装饰器
        // @given('pattern')
        // @when('pattern')  
        // @then('pattern')
        const decoratorRegex = /@(given|when|then)\s*\(\s*['"](.+)['"]\s*\)/i;
        const funcRegex = /def\s+(\w+)\s*\(/;
        
        for (let i = 0; i < lines.length; i++) {
            const decoratorMatch = lines[i].match(decoratorRegex);
            if (!decoratorMatch) continue;
            
            const type = decoratorMatch[1].toLowerCase() as 'given' | 'when' | 'then';
            const pattern = decoratorMatch[2];
            
            // 查找下一行的函数定义
            const funcMatch = lines[i + 1]?.match(funcRegex);
            const functionName = funcMatch?.[1] || `step_${i}`;
            
            // 转换 Behave 模式为 JavaScript 正则
            const regex = PatternConverter.behaveToRegex(pattern);
            const parameters = PatternConverter.extractParameters(pattern);
            
            definitions.push({
                type: type.charAt(0).toUpperCase() + type.slice(1) as any,
                pattern,
                regex,
                functionName,
                filePath,
                lineNumber: i + 1,
                parameters,
            });
        }
        
        return definitions;
    }
}
```

### 5.4 PatternConverter — 模式转换器

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/core/matching/PatternConverter.ts

export class PatternConverter {
    /**
     * 将 Behave/Cucumber 的模式字符串转换为正则表达式。
     * 
     * 转换规则:
     * - {word}        → (\w+)
     * - {int}         → (\d+)
     * - {float}       → (\d+\.?\d*)
     * - {string}      → "([^"]*)"
     * - {anything}    → (.+)
     * - 普通文本       → 原样匹配
     */
    
    static behaveToRegex(pattern: string): RegExp {
        let regexStr = pattern;
        
        // 转义特殊字符
        regexStr = regexStr.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        
        // 替换参数占位符
        regexStr = regexStr.replace(/\\\{word\\\}/g, '(\\w+)');
        regexStr = regexStr.replace(/\\\{int\\\}/g, '(\\d+)');
        regexStr = regexStr.replace(/\\\{float\\\}/g, '(\\d+\\.?\\d*)');
        regexStr = regexStr.replace(/\\\{string\\\}/g, '"([^"]*)"');
        regexStr = regexStr.replace(/\\\{anything\\\}/g, '(.+)');
        
        // 处理可选部分 (...)
        regexStr = regexStr.replace(/\\\(\.\.\.\\\)/g, '(?:.+)?');
        
        return new RegExp(`^${regexStr}$`, 'i');
    }
    
    static extractParameters(pattern: string): string[] {
        const params: string[] = [];
        const paramRegex = /\{(\w+)\}/g;
        let match;
        while ((match = paramRegex.exec(pattern)) !== null) {
            params.push(match[1]);
        }
        return params;
    }
}
```

---

## 六、Provider 层（VS Code UI）

### 6.1 CodeLensProvider — 代码透镜

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/providers/CodeLensProvider.ts

export class FeatureCodeLensProvider implements vscode.CodeLensProvider {
    /**
     * 在 .feature 文件中每个 Scenario 上方显示 CodeLens。
     * 
     * CodeLens 按钮:
     * - "▶ Run" - 运行此 Scenario
     * - "🔍 Find Steps" - 查找匹配的 Step Definition
     * - "🤖 Generate Steps" - AI 生成 Step Definition
     * - "📊 Coverage" - 查看覆盖率
     */
    
    provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
        const lenses: vscode.CodeLens[] = [];
        const feature = this.parser.parse(document.getText(), document.fileName);
        
        for (const scenario of feature.feature.scenarios) {
            const range = new vscode.Range(
                scenario.location.line - 1, 0,
                scenario.location.line - 1, 0
            );
            
            // Run button
            lenses.push(new vscode.CodeLens(range, {
                title: '▶ Run',
                command: 'bdd-ai-toolkit.runScenario',
                arguments: [scenario],
            }));
            
            // Find steps button
            lenses.push(new vscode.CodeLens(range, {
                title: '🔍 Find Steps',
                command: 'bdd-ai-toolkit.findStepDefinitions',
                arguments: [scenario],
            }));
            
            // Generate steps button (only for unmatched steps)
            if (this._hasUnmatchedSteps(scenario)) {
                lenses.push(new vscode.CodeLens(range, {
                    title: '🤖 Generate Steps',
                    command: 'bdd-ai-toolkit.generateStepDefinitions',
                    arguments: [scenario],
                }));
            }
        }
        
        return lenses;
    }
}
```

### 6.2 DecorationProvider — 装饰器

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/providers/DecorationProvider.ts

export class StepDecorationProvider {
    /**
     * 在编辑器中为 Step 添加颜色装饰：
     * - 🟢 绿色: Step 已匹配到 Definition
     * - 🟡 黄色: Step 匹配但参数有问题
     * - 🔴 红色: Step 未匹配到 Definition
     * - ⚪ 灰色: Background step
     */
    
    private matchedDecoration: vscode.TextEditorDecorationType;
    private unmatchedDecoration: vscode.TextEditorDecorationType;
    private ambiguousDecoration: vscode.TextEditorDecorationType;
    
    constructor() {
        this.matchedDecoration = vscode.window.createTextEditorDecorationType({
            backgroundColor: 'rgba(0, 255, 0, 0.1)',
            borderLeft: '3px solid #4CAF50',
        });
        
        this.unmatchedDecoration = vscode.window.createTextEditorDecorationType({
            backgroundColor: 'rgba(255, 0, 0, 0.1)',
            borderLeft: '3px solid #F44336',
        });
        
        this.ambiguousDecoration = vscode.window.createTextEditorDecorationType({
            backgroundColor: 'rgba(255, 255, 0, 0.1)',
            borderLeft: '3px solid #FFEB3B',
        });
    }
    
    updateDecorations(editor: vscode.TextEditor, matchResult: MatchResult) {
        const matchedRanges: vscode.Range[] = [];
        const unmatchedRanges: vscode.Range[] = [];
        const ambiguousRanges: vscode.Range[] = [];
        
        for (const match of matchResult.matches) {
            matchedRanges.push(this._getStepRange(editor, match.step));
        }
        
        for (const step of matchResult.unmatched) {
            unmatchedRanges.push(this._getStepRange(editor, step));
        }
        
        for (const group of matchResult.ambiguous) {
            for (const match of group) {
                ambiguousRanges.push(this._getStepRange(editor, match.step));
            }
        }
        
        editor.setDecorations(this.matchedDecoration, matchedRanges);
        editor.setDecorations(this.unmatchedDecoration, unmatchedRanges);
        editor.setDecorations(this.ambiguousDecoration, ambiguousRanges);
    }
}
```

### 6.3 WebviewProvider — Webview 面板

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/providers/WebviewProvider.ts

export class AutomationDetailsProvider implements vscode.WebviewViewProvider {
    /**
     * 在 VS Code 侧边栏显示自动化测试详情面板。
     * 
     * 面板内容:
     * - Feature 文件列表
     * - Scenario 执行状态
     * - Step 匹配状态
     * - 最近的测试运行结果
     */
    
    resolveWebviewView(webviewView: vscode.WebviewView) {
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(this.context.extensionUri, 'resources'),
            ],
        };
        
        webviewView.webview.html = this._getHtml();
        
        // 处理来自 Webview 的消息
        webviewView.webview.onDidReceiveMessage(message => {
            switch (message.command) {
                case 'runScenario':
                    vscode.commands.executeCommand('bdd-ai-toolkit.runScenario', message.scenario);
                    break;
                case 'generateSteps':
                    vscode.commands.executeCommand('bdd-ai-toolkit.generateStepDefinitions', message.scenario);
                    break;
            }
        });
    }
}
```

---

## 七、Services 层（业务逻辑）

### 7.1 AutomationStatusService — 自动化状态服务

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/services/AutomationStatusService.ts

export class AutomationStatusService {
    /**
     * 管理每个 Scenario/Step 的自动化状态。
     * 
     * 状态流转:
     *   NOT_AUTOMATED → IN_PROGRESS → AUTOMATED
     *                                 → FAILED
     */
    
    async getScenarioStatus(featureFile: string, scenarioName: string): Promise<AutomationStatus> {
        return this.cache.get(`${featureFile}:${scenarioName}`);
    }
    
    async updateScenarioStatus(featureFile: string, scenarioName: string, status: AutomationStatus): Promise<void> {
        await this.cache.set(`${featureFile}:${scenarioName}`, status);
        this._notifyStatusChange();
    }
    
    async getOverallStats(): Promise<AutomationStats> {
        const allStatuses = await this.cache.getAll();
        const total = allStatuses.size;
        const automated = Array.from(allStatuses.values()).filter(s => s === 'AUTOMATED').length;
        
        return {
            total,
            automated,
            percentage: total > 0 ? (automated / total) * 100 : 0,
        };
    }
}

type AutomationStatus = 'NOT_AUTOMATED' | 'IN_PROGRESS' | 'AUTOMATED' | 'FAILED';
```

### 7.2 CopilotIntegrationService — Copilot 集成

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/services/CopilotIntegrationService.ts

export class CopilotIntegrationService {
    /**
     * 通过 MCP 协议与 GitHub Copilot 集成。
     * 
     * 功能:
     * 1. 向 Copilot 发送上下文信息
     * 2. 让 Copilot 生成 Step Definition 代码
     * 3. 让 Copilot 执行 UI 操作（通过 MCP Server）
     */
    
    async generateStepDefinition(step: GherkinStep): Promise<string> {
        const prompt = this._buildStepGenerationPrompt(step);
        
        // 通过 VS Code Language Model API 调用 Copilot
        const [model] = await vscode.lm.selectChatModels({
            vendor: 'copilot',
            family: 'gpt-4o',
        });
        
        if (!model) {
            throw new Error('Copilot chat model not available');
        }
        
        const messages = [
            vscode.LanguageModelChatMessage.User(prompt),
        ];
        
        const response = await model.sendRequest(messages, {});
        let result = '';
        for await (const fragment of response.text) {
            result += fragment;
        }
        
        return result;
    }
    
    async executeUICommand(command: string): Promise<any> {
        // 通过 MCP 协议发送 UI 命令
        // Copilot → MCP Client → MCP Server → pywinauto/Appium
    }
}
```

### 7.3 DryRunService — 干运行服务

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/services/DryRunService.ts

export class DryRunService {
    /**
     * 执行 Behave dry-run 以检查 Step 匹配状态。
     * 调用 `behave --dry-run` 命令并解析输出。
     */
    
    async runDryRun(featureFile: string): Promise<DryRunResult> {
        const command = `behave --dry-run --no-summary "${featureFile}"`;
        const output = await this._executeCommand(command);
        
        return this._parseDryRunOutput(output);
    }
    
    private _parseDryRunOutput(output: string): DryRunResult {
        const result: DryRunResult = {
            passed: [],
            failed: [],
            skipped: [],
            undefined: [],
        };
        
        const lines = output.split('\n');
        for (const line of lines) {
            if (line.includes('PASSED')) {
                result.passed.push(line);
            } else if (line.includes('FAILED')) {
                result.failed.push(line);
            } else if (line.includes('SKIPPED')) {
                result.skipped.push(line);
            } else if (line.includes('UNDEFINED')) {
                result.undefined.push(line);
            }
        }
        
        return result;
    }
}
```

---

## 八、缓存层（`cache/`）

### 8.1 UnifiedCacheManager — 统一缓存管理

```typescript
// 位置: bdd_ai_toolkit/src/bdd-feature-support/cache/UnifiedCacheManager.ts

export class UnifiedCacheManager {
    /**
     * 统一管理所有缓存，提供 TTL、失效策略和持久化。
     */
    
    private caches: Map<string, BaseCache<any>> = new Map();
    
    constructor() {
        this.caches.set('automation-status', new AutomationStatusCache());
        this.caches.set('python-files', new PythonFileCache());
        this.caches.set('step-matches', new StepMatchCache());
    }
    
    getCache<T>(name: string): BaseCache<T> {
        return this.caches.get(name) as BaseCache<T>;
    }
    
    async clearAll(): Promise<void> {
        for (const cache of this.caches.values()) {
            await cache.clear();
        }
    }
    
    async invalidateByFile(filePath: string): Promise<void> {
        // 当文件变更时，失效相关缓存
        for (const cache of this.caches.values()) {
            await cache.invalidate(filePath);
        }
    }
}
```

---

## 九、Setup 模块（环境安装向导）

### 9.1 `environment.ts` — 环境检测

```typescript
// 位置: bdd_ai_toolkit/src/setup/environment.ts

export class EnvironmentDetector {
    /**
     * 检测开发环境：
     * - Python 版本和路径
     * - pip/uv 包管理器
     * - Node.js 版本
     * - Git 可用性
     * - Appium 服务器状态
     */
    
    async detectAll(): Promise<EnvironmentInfo> {
        return {
            python: await this._detectPython(),
            node: await this._detectNode(),
            git: await this._detectGit(),
            appium: await this._detectAppium(),
            platform: this._detectPlatform(),
        };
    }
}
```

### 9.2 `mcpServerManager.ts` — MCP 服务器管理

```typescript
// 位置: bdd_ai_toolkit/src/setup/mcpServerManager.ts

export class MCPServerManager {
    /**
     * 管理 MCP 服务器的安装、配置和启动。
     * 
     * 支持的 MCP 服务器:
     * - pywinauto-mcp-server (Windows)
     * - appium-mcp-server (macOS/Mobile)
     */
    
    async installServer(serverType: 'pywinauto' | 'appium'): Promise<void> {
        const serverPath = this._getServerPath(serverType);
        const config = this._getServerConfig(serverType);
        
        // 安装 Python 依赖
        await this._installDependencies(serverPath);
        
        // 配置 MCP 服务器
        await this._configureServer(serverType, config);
        
        // 测试连接
        await this._testConnection(serverType);
    }
    
    async startServer(serverType: 'pywinauto' | 'appium'): Promise<void> {
        const serverPath = this._getServerPath(serverType);
        // 通过终端启动 MCP 服务器
    }
}
```

---

## 十、提示词模块（`constants/prompts.ts`）

```typescript
// 位置: bdd_ai_toolkit/src/constants/prompts.ts

export const SYSTEM_PROMPT = `
You are an expert in Behavior-Driven Development (BDD) and test automation.
Your task is to help create high-quality Gherkin feature files and step definitions.

## Guidelines for Feature Files:
1. Use clear, descriptive Feature names
2. Write Scenarios that are independent and isolated
3. Use Scenario Outlines for data-driven tests
4. Add meaningful tags (@smoke, @regression, @ui, @api)
5. Keep steps atomic - one action per step
6. Use declarative style over imperative

## Guidelines for Step Definitions:
1. Write reusable step definitions
2. Use parameterization for dynamic values
3. Follow the project's existing patterns
4. Add proper error handling and logging
`;

export const TEST_CASE_GENERATION_PROMPT = `
Generate BDD test scenarios in Gherkin format based on the following context.

## Requirements:
- Cover happy path, edge cases, and error scenarios
- Include Scenario Outlines with Examples where appropriate
- Add meaningful tags
- Write steps in declarative style

## Context:
{context}

## Output Format:
\`\`\`gherkin
Feature: ...
  ...
\`\`\`
`;
```

---

## 十一、核心数据流

```
用户操作 VS Code
        │
        ├── 编辑 .feature 文件
        │       │
        │       ▼
        │   FeatureParser.parse()     → GherkinDocument
        │       │
        │       ▼
        │   StepExtractor.extractAllSteps()
        │       │
        │       ▼
        │   StepDefinitionLoader.load() → StepDefinition[]
        │       │
        │       ▼
        │   StepMatcher.match()        → MatchResult
        │       │
        │       ├──► DecorationProvider (编辑器高亮)
        │       ├──► CodeLensProvider  (CodeLens 按钮)
        │       └──► WebviewProvider   (侧边栏面板)
        │
        ├── 执行命令 (generateTestCase / executeNaturalLanguageTask)
        │       │
        │       ▼
        │   TestCaseGenerator / NaturalLanguageTaskExecutor
        │       │
        │       ▼
        │   LLM (Copilot / OpenAI)
        │       │
        │       ▼
        │   生成 Gherkin / Step Definition 代码
        │
        └── 安装向导
                │
                ▼
            SetupWebViewProvider
                │
                ├── EnvironmentDetector
                ├── MCPServerManager
                └── PythonEnvironmentManager
```

## 十二、VS Code 命令列表

| 命令 ID | 功能 |
|---------|------|
| `bdd-ai-toolkit.generateTestCase` | 从多种输入生成测试用例 |
| `bdd-ai-toolkit.executeNaturalLanguageTask` | 自然语言任务执行 |
| `bdd-ai-toolkit.generateFromFigma` | 从 Figma 生成测试 |
| `bdd-ai-toolkit.generateFromXMind` | 从 XMind 生成测试 |
| `bdd-ai-toolkit.openSetupWizard` | 打开安装向导 |
| `bdd-ai-toolkit.runScenario` | 运行 Scenario |
| `bdd-ai-toolkit.findStepDefinitions` | 查找 Step 定义 |
| `bdd-ai-toolkit.generateStepDefinitions` | AI 生成 Step 定义 |
