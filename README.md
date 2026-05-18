# 微信读书自动阅读机器人

一个简洁的微信读书自动阅读工具，通过模拟阅读请求来积累阅读时长。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 获取 CURL 命令

1. 在电脑上打开微信读书网页版 https://weread.qq.com/
2. 登录账号，开始阅读一本书
3. 打开浏览器开发者工具 (F12) -> Network (网络)
4. 找到 `read` 请求，复制为 cURL
5. 保存到 `curl_command.txt`

### 3. 运行

```bash
python weread-bot.py -c curl_command.txt -t 60 -i 30
```

参数说明：
- `-c, --curl`: CURL命令文件路径 (默认: curl_command.txt)
- `-t, --target`: 目标阅读时长(分钟) (默认: 60)
- `-i, --interval`: 请求间隔(秒) (默认: 30)
- `-v, --verbose`: 显示详细日志

## 使用方式

```bash
# 阅读60分钟，间隔30秒
python weread-bot.py -t 60 -i 30

# 阅读30分钟，间隔20秒
python weread-bot.py -t 30 -i 20

# 详细模式
python weread-bot.py -v
```

## 项目结构

```
weread-bot/
├── weread-bot.py         # 入口脚本
├── requirements.txt     # 依赖(仅requests)
├── curl_command.txt     # CURL命令(需自行抓取)
├── README.md
├── LICENSE
├── AGENTS.md
└── weread_bot/
    ├── __init__.py
    ├── __main__.py
    └── weread.py         # 核心逻辑
```

## 注意事项

- CURL 命令中的 cookie 会过期，过期后需重新抓取
- 建议设置合理的间隔时间(20-40秒)，过短可能被检测
- 目标时长建议45-90分钟，符合正常阅读习惯