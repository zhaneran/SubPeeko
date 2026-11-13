# SubPeeko

[English README](README.md)

<p>
<a href="https://github.com/zhaneran/SubPeeko/actions/workflows/tests.yml?query=branch%3Amain"><img src="https://github.com/zhaneran/SubPeeko/actions/workflows/tests.yml/badge.svg?branch=main" alt="构建状态"></a>
<a href="https://github.com/zhaneran/SubPeeko/releases"><img src="https://img.shields.io/github/v/release/zhaneran/SubPeeko?display_name=tag" alt="最新版本"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/zhaneran/SubPeeko" alt="许可证"></a>
</p>

SubPeeko 可以将双语英中 ASS 字幕转换为英语学习字幕。它保留原始英文，
并把中文对白替换为高于所选学习等级的词汇、短语、语法和语境用法说明。

当前版本为 `0.1.0`，发布记录见 [RELEASES.md](RELEASES.md)。构建和发布流程见
[BUILD.md](BUILD.md)。

## 安装

项目要求 Python 3.10 或更高版本。安装本地源码：

```bash
python -m pip install .
```

如果使用虚拟环境，请先激活虚拟环境。发布到 PyPI 后，可以使用下面的命令安装：

```bash
python -m pip install subpeeko
```

## 配置模型

```bash
subpeeko config       # 交互式设置 API 根地址、模型名和 API Key
subpeeko config show  # 显示设置，不显示 API Key
subpeeko config test  # 发送一个小请求检查连接
```

API 需要支持 OpenAI 兼容的 Chat Completions。`base_url` 应填写服务商的 API 根地址，
例如 `https://example.com/v1`，不要在末尾添加 `/chat/completions`。连接测试会发送真实请求，
服务商可能会收取费用。

模型名和 API 根地址保存在用户配置目录中。API Key 优先保存在系统凭据库中。如果系统没有可用的
凭据库，可以设置 `SUBPEEKO_API_KEY` 环境变量。非交互环境可以设置下面三个变量：

```text
SUBPEEKO_BASE_URL=https://example.com/v1
SUBPEEKO_MODEL_NAME=your-model
SUBPEEKO_API_KEY=your-api-key
```

环境变量优先于当前目录的 `.env` 文件，`.env` 文件优先于已保存的配置。不要把真实的 `.env`
文件提交到 Git，也不要把 API Key 写在命令行参数中。可以参考 [.env.example](.env.example)。

## 转换字幕

```bash
subpeeko "movie.ass" --level cet4
subpeeko "./subtitles" --level cet4
subpeeko "./subtitles" --level cet4 --recursive
```

学习等级按累积难度排列：`highschool`、`cet4`、`cet6`、`postgrad`。生成文件会放在输入文件旁边，
例如 `movie.cet4.subpeeko.ass`。输入文件不会被覆盖。已有生成文件只有在指定 `--overwrite` 时才会替换，
目录扫描时会自动跳过已生成文件。目录默认不递归扫描。

使用 `--dry-run` 可以只列出输入和输出路径，不发送模型请求，也不写入文件。批量处理时，单个文件的错误
会被单独报告，其他文件仍会继续处理。只要有文件失败，命令就会返回非零退出状态。

### 处理参数

`--batch-size N` 设置每个模型请求包含的目标对白数量，默认值为 5，可设置为 1 到 100。它和
`--concurrency` 相互独立，后者控制同时执行的请求数量。每个请求还会附带附近对白作为上下文，因此实际
请求中的对白行数可能多于目标批次大小。

增大批次可以减少请求次数，但会产生更大的请求内容和更大的失败单元。减小批次可以缩小失败影响范围，
但会增加请求次数。超时、输出不完整或格式错误的批次会被拆分并重试，后续批次仍使用原来的批次大小。

```bash
subpeeko "movie.ass" --level cet4 --batch-size 20 --concurrency 4
subpeeko "movie.ass" --level cet4 --batch-size 1 --concurrency 5
```

第一条命令表示每个请求最多处理 20 条目标对白，同时最多运行 4 个请求。第二条命令表示每个请求处理 1 条
目标对白，同时最多运行 5 个请求。

所有 OpenAI 兼容接口默认发送 `enable_thinking: false`。使用 `--thinking on` 开启思考，或使用
`--thinking auto` 省略这个服务商扩展参数并使用服务商默认行为。如果服务商不接受 `enable_thinking`，
可以使用 `auto` 模式。

默认最多同时处理 4 个批次。默认进程预算为每分钟 60 个请求和 5,000,000 个输入及输出 Token。可以单独调整：

```bash
subpeeko "movie.ass" --level cet4 --concurrency 2 --rpm 30 --tpm 500000 --qps 0.5
subpeeko "movie.ass" --level cet4 --concurrency 1
```

`--qps` 可选，且不会超过 `RPM / 60`。限流器会使用配置配额的 80%，并为每次请求和重试预留估算的输入、
输出 Token。`--max-output-tokens` 默认值为 2048。思考模式开启时，可以用 `--reasoning-reserve` 调整没有
合并上限的服务商的额外思考 Token 预留。

程序会报告每次请求的目标数量、网络耗时、限流等待、状态和服务商返回的 Token 用量。日志不会打印字幕文本
或 API Key。已完成的批次会写入本地检查点，重新执行相同命令可以从中断位置继续。使用 `--no-resume` 可以
禁用检查点读写。

Windows 检查点目录为 `%LOCALAPPDATA%\subpeeko\checkpoints`，Linux 检查点目录为
`${XDG_CACHE_HOME:-~/.cache}/subpeeko/checkpoints`。

## 工作方式

程序会把原始中文、附近对白和本地计算的词汇提示一起发送给配置的模型。模型返回高于所选等级的语言点说明，
程序再把说明写入新的 ASS 文件。

程序会保留原始事件时间、英文、样式、元数据和其他事件。它会处理中文和英文位于连续 ASS 行组中的双语对白。
单行混合语言或其他无法可靠识别的布局会保持不变。输入文件为 UTF-8、带 BOM 的 UTF-16 或 GB18030 时，
程序会保留对应编码。模型响应不完整或无效时，不会为该文件写入结果。

## 词库来源和更新

内置词库来自 [KyleBing/english-vocabulary](https://github.com/KyleBing/english-vocabulary)，
其词库许可证和来源说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。每次构建源码包或 wheel 时，
程序都会检查上游词库是否有新版本，并在可用时把更新后的词库写入构建产物。安装后的 SubPeeko 不会在运行时下载词库。

## 发布、构建和许可证

SubPeeko 源代码使用 MIT 许可证，详见 [LICENSE](LICENSE)。随包提供的词库数据是独立的第三方数据，
请同时阅读 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 及包内的 KyleBing 许可证文件。

构建源码包和 wheel：

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

发布版本、构建产物和发布检查清单见 [RELEASES.md](RELEASES.md) 与 [BUILD.md](BUILD.md)。

## 开发

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```
