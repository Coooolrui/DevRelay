# DevRelay

DevRelay 是一个面向前端联调的本地代理工具。

它让专用 Chrome 或 Edge 浏览器继续访问测试环境页面，同时把指定接口请求转发到本机服务。HTTPS 请求由 mitmproxy 在本地解密，再通过 HTTP 连接本地服务，不需要修改测试环境，也不需要把本地服务部署到测试环境。

## 工作方式

```text
测试环境页面
    |
    | 专用 Chrome / Edge
    v
127.0.0.1:8080  DevRelay / mitmproxy
    |
    | 规则匹配、HTTPS 解密、路径重写、Header 与 CORS 处理
    v
http://localhost:7890  本地业务服务
```

项目包含两个本地服务：

- **管理服务**：Web 控制台，默认地址 `http://127.0.0.1:8787`。
- **代理服务**：mitmproxy，默认监听 `127.0.0.1:8080`。

管理服务不会自动启动代理。代理端口和本地业务端口必须不同。

## 支持能力

- Windows 和 macOS。
- Chrome 和 Edge 独立浏览器 profile。
- HTTP、HTTPS、WebSocket、SSE、文件上传和长连接。
- 按域名、路径、方法匹配规则，使用 Python 正则表达式。
- 路径重写。
- 请求头和响应头增加、覆盖、删除。
- `$origin`、`$host`、`$path`、`$query`、`$method` 内置变量。
- Python 命名捕获变量，例如 `(?P<userId>[^/]+)` 和 `${userId}`。
- CORS 响应头和 `OPTIONS` 预检处理。
- 多 YAML 配置文件选择、排序、导入、复制、重命名和删除。
- Web 控制台表单编辑、YAML 编辑、状态查看、日志和本地服务检测。

当前不修改响应体，也不会自动启动你的本地业务服务。

## 安装

需要安装 [uv](https://docs.astral.sh/uv/)。

macOS/Linux：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

进入当前目录后安装 Python 和项目依赖：

```bash
uv python install 3.12
uv sync
```

项目使用 Python 3.12，依赖由 uv 管理。首次安装需要联网；安装完成后，代理和证书页面在本机运行。

## 第一次启动

### 1. 启动本地业务服务

先启动你的服务，例如：

```text
http://localhost:7890
```

端口可以按项目实际情况修改，配置文件中的 `target.port` 必须一致。

### 2. 启动管理服务

```bash
uv run python devrelay_agent.py
```

默认打开 `http://127.0.0.1:8787`。不自动打开浏览器时：

```bash
uv run python devrelay_agent.py --no-open
```

管理页面启动后：

1. 在“代理配置”中勾选要生效的 YAML 文件，调整顺序并保存选择。
2. 在“代理控制”中设置代理端口，默认 `8080`。
3. 点击“启动代理”。
4. 首次使用时打开证书页并安装 mitmproxy CA 证书。
5. 按需启动专用 Chrome 或 Edge，浏览器会打开空白页，之后由用户输入目标地址。

第一次打开控制台会自动显示初始化向导，向导也可以从页面顶部重新打开。向导只负责环境、代理和证书就绪，不要求填写目标地址或创建规则；浏览器按需从主控制台启动。

## HTTPS 证书

HTTPS 转发需要代理解密 TLS，因此专用浏览器必须信任一次 mitmproxy CA。证书页面是代理在本机提供的 `http://mitm.it`，安装证书不需要访问外部网站。

### macOS

在控制台点击“打开证书页”，或运行：

```bash
uv run python launch_browser.py \
  --browser chrome \
  --profile-dir .profiles \
  --url http://mitm.it
```

下载证书后，在“钥匙串访问”中将 `mitmproxy` 证书加入“登录”钥匙串，并将“使用此证书时”设为“始终信任”。

### Windows

打开 `http://mitm.it` 下载证书，导入 Windows 的“受信任的根证书颁发机构”。

安装后完全退出并重新启动专用浏览器。日常浏览器和系统代理不会被修改。

## 启动专用浏览器

Chrome：

```bash
uv run python launch_browser.py \
  --browser chrome \
  --profile-dir .profiles \
  --url about:blank
```

Edge：

```bash
uv run python launch_browser.py \
  --browser edge \
  --profile-dir .profiles \
  --url about:blank
```

启动器会设置：

- `--user-data-dir=.profiles`：独立 Cookie、缓存和扩展目录。
- `--proxy-server=http=127.0.0.1:8080;https=127.0.0.1:8080`：只让这个浏览器使用 DevRelay。
- `--proxy-bypass-list=<-loopback>`：确保本地调试请求也经过代理。

## 配置文件

配置文件放在 `configs/`，根对象必须包含 `rules` 数组。控制台可以同时勾选多个文件并调整顺序；代理按文件顺序、文件内规则顺序匹配，第一条命中的规则生效。

没有选择任何配置文件时，代理禁止启动。

### 最小示例

```yaml
rules:
  - name: api-to-local
    enabled: true
    match:
      host: '^api\\.example\\.com$'
      path: '^/api(?:/|$)'
      method: '^(GET|POST|PUT|PATCH|DELETE|OPTIONS)$'
    target:
      host: localhost
      port: 7890
```

### 匹配规则

```yaml
match:
  host: '^api\\.example\\.com$'
  path: '^/api(?:/|$)'
  method: '^(GET|POST|OPTIONS)$'
```

- `host` 只写域名，不写协议和路径。
- `path` 匹配请求路径，需要时可以把查询字符串纳入正则。
- `method` 匹配 HTTP 方法。跨域请求需要预检时，必须包含 `OPTIONS`。
- 规则命中只看域名、路径和方法。Header 改动在命中后执行，不参与命中判断。

### 本地目标和 Host

```yaml
target:
  host: localhost
  port: 7890
preserveHost: false
```

本地目标统一使用 HTTP。浏览器发来的 HTTP、HTTPS、WS 或 WSS 请求，命中后都可以转发到本地 HTTP 服务。

`preserveHost: false` 时，本地服务收到 `Host: localhost:7890`。只有本地服务依赖远程域名做虚拟主机路由时，才设置：

```yaml
preserveHost: true
```

### 路径重写

```yaml
rewritePath:
  pattern: '^/api'
  replacement: ''
```

请求 `/api/v1/users` 转发到本地时会变成 `/v1/users`。

### 请求头和响应头

规则命中后，可以分别修改请求和响应 Header：

```yaml
requestHeaders:
  - action: add
    name: X-DevRelay-Local
    value: '1'
  - action: set
    name: Authorization
    value: 'Bearer local-token'
  - action: remove
    name: X-Remote-Only

responseHeaders:
  - action: set
    name: X-User-Id
    value: '${userId}'
```

- `add`：增加 Header，同名 Header 可以追加。
- `set`：覆盖已有 Header。
- `remove`：删除 Header，不需要填写 `value`。

Header 值支持 `$origin`、`$host`、`$path`、`$query`、`$method` 等内置变量，也支持命名捕获变量：

```yaml
match:
  path: '^/users/(?P<userId>[^/]+)$'
responseHeaders:
  - action: set
    name: X-User-Id
    value: '${userId}'
```

请求 `/users/42` 时，`${userId}` 的值是 `42`。

### CORS

启用后，代理会为匹配规则的响应增加 CORS 响应头，并直接处理 `OPTIONS` 预检请求，返回 `204`：

```yaml
cors:
  enabled: true
  allowOrigin: 'https://apifox.com'
  allowCredentials: true
  allowMethods: 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
  allowHeaders: 'Content-Type, Authorization, X-Requested-With'
  maxAge: 600
```

- `allowOrigin` 写前端页面 Origin，不是接口域名，也不要带路径。
- `allowOrigin: '$origin'` 会回显当前请求的 Origin，适合本地调试。
- `allowCredentials: true` 允许 Cookie 等登录态跨域发送；此时 `allowOrigin` 不能是 `*`。
- `allowMethods` 是预检允许的方法列表。
- `allowHeaders` 是预检允许的请求头列表，不负责主动增加请求头。
- `maxAge` 是预检结果缓存秒数。

关闭 CORS：

```yaml
cors:
  enabled: false
```

## 手动启动代理

正常使用推荐从 Web 控制台启动。排查问题时可以直接运行 mitmproxy：

```bash
uv run mitmdump \
  -p 8080 \
  -s devrelay_proxy.py \
  --set 'devrelay_configs=["configs/default.yml"]'
```

看到 `HTTP(S) proxy listening at *:8080` 后保持终端运行。修改 YAML 后，代理会在下一次请求时重新加载；修改 Python 代码后需要重启 mitmproxy。

## 常见问题

### 证书错误

在当前专用浏览器对应的系统证书存储中信任 mitmproxy CA，并完全重启专用浏览器。

### CORS 预检失败

检查规则是否包含 `OPTIONS`，`cors.enabled` 是否为 `true`，`allowOrigin` 是否与前端页面 Origin 完全一致，以及 `allowHeaders` 是否包含浏览器实际声明的请求头。使用凭证时不能把 `allowOrigin` 写成 `*`。

### 代理没有命中规则

检查配置文件是否勾选并保存选择；`host` 是否只写域名；`path` 和 `method` 是否匹配实际请求；本地服务是否已启动且端口正确。

## 项目结构

```text
.
├── devrelay_agent.py    # Web 管理服务
├── devrelay_proxy.py    # mitmproxy 转发插件
├── launch_browser.py    # 启动独立 Chrome/Edge
├── rules.py              # YAML 解析、规则匹配和变量捕获
├── configs/              # YAML 规则文件
├── ui/index.html         # Web 控制台
├── tests/                # Python 单元测试
├── guide.md              # 详细操作手册
└── pyproject.toml        # uv 项目配置
```

## 开发与测试

```bash
uv run python -m unittest discover -s tests -v
uv run python -m py_compile devrelay_agent.py devrelay_proxy.py rules.py
```

更详细的操作步骤见 [guide.md](./guide.md)。
