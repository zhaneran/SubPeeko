# SubPeeko

[English README](README.md)

<p>
<a href="https://github.com/zhaneran/SubPeeko/actions/workflows/tests.yml?query=branch%3Amain"><img src="https://github.com/zhaneran/SubPeeko/actions/workflows/tests.yml/badge.svg?branch=main" alt="构建状态"></a>
<a href="https://github.com/zhaneran/SubPeeko/releases"><img src="https://img.shields.io/github/v/release/zhaneran/SubPeeko?display_name=tag" alt="最新版本"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/zhaneran/SubPeeko" alt="许可证"></a>
</p>

SubPeeko 可以把双语英中 ASS 字幕转换为英语学习字幕。它保留原始英文，
并在下面加入高于所选学习等级的简洁中文说明。

## 效果示例

SubPeeko 会把常见的“中文在上、英文在下”改成英文优先布局：

| 处理前（中文 / 英文） | 处理后（英文 / 说明） |
| --- | --- |
| 中文翻译<br>*This appears to be a misunderstanding.* | *This appears to be a misunderstanding.*<br>**misunderstanding: 误会； appears: 似乎** |
| 他们暂缓了提案<br>*They tabled the proposal.* | *They tabled (暂缓) the proposal.*<br>**tabled: 暂缓（提案）** |
| 我需要再想想<br>*I need to mull it over.* | *I need to mull it over.*<br>**mull it over: 仔细考虑** |

如果原始中文字幕字号更大，生成字幕还会交换中英文两行的字号。

## 安装

需要 Python 3.10 或更高版本：

```bash
python -m pip install subpeeko
```

从源码目录安装：

```bash
python -m pip install .
```

## 配置模型

交互式设置 API 根地址、模型名和 API Key：

```bash
subpeeko config
subpeeko config show
subpeeko config test
```

API 需要支持 OpenAI 兼容的 Chat Completions。API 根地址例如
`https://example.com/v1`，末尾不要添加 `/chat/completions`。连接测试会发送真实请求。

脚本或 CI 环境可以设置：

```text
SUBPEEKO_BASE_URL=https://example.com/v1
SUBPEEKO_MODEL_NAME=your-model
SUBPEEKO_API_KEY=your-api-key
```

也可以使用当前目录下可选的 `.env` 文件。不要把真实 Key 提交到 Git，
也不要把 Key 写在命令行参数中。

## 转换字幕

转换单个文件：

```bash
subpeeko "movie.ass" --level cet4
```

转换目录，或递归处理子目录：

```bash
subpeeko "./subtitles" --level cet4
subpeeko "./subtitles" --level cet4 --recursive
```

学习等级按累积难度排列：`highschool`、`cet4`、`cet6`、`postgrad`。
结果会写在输入文件旁边，例如 `movie.cet4.subpeeko.ass`，输入文件不会被覆盖。

常用选项：

| 选项 | 用途 |
| --- | --- |
| `--recursive` | 目录输入时包含子目录。 |
| `--overwrite` | 替换已经存在的生成文件。 |
| `--dry-run` | 只列出输入和输出路径，不调用模型、不写文件。 |
| `--batch-size N` | 设置每次请求处理的目标对白数量。 |
| `--concurrency N` | 设置同时执行的请求数量。 |
| `--no-resume` | 忽略已保存进度，从头开始。 |
| `--thinking {off,on,auto}` | 选择模型思考模式。 |

查看全部选项：

```bash
subpeeko --help
```

## 输出行为

- 英文在上，生成的中文说明在下。
- 简短释义会内嵌在英文词组后，完整说明仍保留在下方。
- 原始时间轴、英文、编码和无关 ASS 事件会保留。
- 无法可靠识别的字幕布局保持不变。
- 如果输出文件已经存在，必须指定 `--overwrite` 才会替换。
- `subpeeko config show` 会隐藏 API Key。

SubPeeko 使用 [MIT 许可证](LICENSE) 发布。
