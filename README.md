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
      host: '^api\.example\.com$'
      path: '^/api(?:/|\?|$)'
      method: '^(GET|POST|PUT|PATCH|DELETE|OPTIONS)$'
    target:
      host: localhost
      port: 7890
```

这条规则命中 `http://api.example.com/api/v1/users` 和 `http://api.example.com/api?page=1`，转发到 `http://localhost:7890`。`/api` 以外的页面和接口继续访问原服务器。

### 匹配规则

一条规则先看 `enabled`，再同时比较 `match.host`、`match.path`、`match.method`。三个字段都通过才算命中。某个字段留空或不写，表示这一维不限制。

`enabled: false` 的规则直接跳过。多个配置文件按控制台里的勾选顺序合并，再按文件内的书写顺序查找，第一条命中的规则生效，后面的规则不再看。没有规则命中时，请求按原地址发给测试环境。

命中只看下面三个字符串。请求头、Cookie、请求体、协议和端口都不参与判断。请求头的增删改在命中之后才执行。

| 字段 | 拿来比较的字符串 | 请求 `http://192.0.2.10:8080/dev-api/shop/api/orders/search?pageIndex=1&keyword=demo` |
| --- | --- | --- |
| `host` | 主机名或 IP，不含协议、端口、路径 | `192.0.2.10` |
| `path` | 路径，后面紧跟查询字符串 | `/dev-api/shop/api/orders/search?pageIndex=1&keyword=demo` |
| `method` | 大写的 HTTP 方法 | `GET` |

三个字段的值都是 Python 正则，用 `re.search` 查找，不是整串相等。

- 不写 `^` 时，模式出现在字符串任意位置都算命中。`path: /api` 会命中 `/dev-api/shop/api/...`。限定前缀时以 `^` 开头。
- 要求整串一致时，同时写 `^` 和 `$`。
- `.` 表示任意一个字符。域名和 IP 里的点写成 `\.`，否则 `192.0.2.10` 也能命中 `192a0b2c10`。
- 区分大小写。方法按浏览器发出的大写字母写，例如 `GET`。
- YAML 单引号里的反斜杠原样保留。正则需要一个反斜杠时就写一个：`'^api\.example\.com$'`。写成 `'^api\\.example\\.com$'` 时，模式里是两个反斜杠，点号匹配不到。

#### `host`

只写主机名或 IP：

```yaml
host: '^api\.example\.com$'
host: '^192\.0\.2\.10$'
```

`http://192.0.2.10:8080/...` 的 `host` 是 `192.0.2.10`。把端口、`http://` 或路径写进 `host` 后，这条规则匹配不到。规则也不能按端口区分同一台机器；同一 IP 上的不同服务，用 `path` 分开。

#### `path`

`path` 含查询字符串。前缀规则要同时接住「后面还有路径」「后面是 `?`」「路径到此结束」三种情况：

```yaml
path: '^/dev-api/shop(?:/|\?|$)'
```

对 `http://192.0.2.10:8080` 上的请求，这条模式的结果是：

| 实际 `path` | 结果 |
| --- | --- |
| `/dev-api/shop/api/orders/search?pageIndex=1&keyword=demo` | 命中 |
| `/dev-api/shop?status=open` | 命中 |
| `/dev-api/shop` | 命中 |
| `/web/orders/detail` | 不命中，页面继续打开测试环境 |

查询参数会随请求原样转发，`keyword` 这类参数不用写进规则。只有要按某个参数决定是否转发时，才把查询字符串写进正则，例如 `pageIndex=`。

下面几种写法匹配不到上面的搜索接口：

- `^/dev-api/shop/(?:/|$)`：`shop` 后面多要求一个斜杠，`/dev-api/shop/api/...` 对不上。
- `^/dev-api/shop$`：查询字符串还在，字符串没有在 `shop` 处结束。
- `^/api(?:/|$)`：`/api?page=1` 里 `api` 后面是 `?`，既不是 `/` 也不是结尾；它也覆盖不到 `/dev-api/shop` 这个前缀。
- `/api`：没有 `^`，`/dev-api/...` 和 `/other/api` 都会命中。

#### `method`

```yaml
method: '^(GET|POST|PUT|PATCH|DELETE|OPTIONS)$'
```

浏览器跨域时会先发 `OPTIONS` 预检。规则里没有 `OPTIONS` 时，预检继续去测试环境，本地接口收不到后续请求。页面和接口在同一台主机上时通常没有预检。WebSocket 握手的方法是 `GET`。不写 `method` 时，所有方法都通过这一维。

#### 只把同一页面上的接口转到本地

页面 `http://192.0.2.10:8080/web/orders/detail` 和接口 `http://192.0.2.10:8080/dev-api/shop/api/orders/search?pageIndex=1&keyword=demo` 主机相同。`host` 写成这台机器，`path` 只圈接口前缀，页面仍走测试环境：

```yaml
rules:
  - name: shop-api-to-local
    enabled: true
    match:
      host: '^192\.0\.2\.10$'
      path: '^/dev-api/shop(?:/|\?|$)'
      method: '^(GET|POST|PUT|PATCH|DELETE|OPTIONS)$'
    target:
      host: localhost
      port: 7890
    preserveHost: false
    rewritePath:
      pattern: '^/dev-api/shop'
      replacement: ''
```

搜索接口会转发为 `http://localhost:7890/api/orders/search?pageIndex=1&keyword=demo`。`7890` 改成本地服务实际监听的端口。本地接口本身带 `/dev-api/shop` 前缀时，删掉 `rewritePath`。

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
  --ssl-insecure \
  -s devrelay_proxy.py \
  --set 'devrelay_configs=["configs/default.yml"]'
```

`--ssl-insecure` 用于忽略代理连接上游 HTTPS 服务时的证书校验，适合自签名或证书链不完整的测试环境。它不会替代浏览器对 mitmproxy CA 证书的信任。看到 `HTTP(S) proxy listening at *:8080` 后保持终端运行。修改 YAML 后，代理会在下一次请求时重新加载；修改 Python 代码后需要重启 mitmproxy。

DevRelay 默认将客户端连接空闲超时设为 `86400` 秒（24 小时），避免浏览器长时间不用后复用被代理关闭的连接。需要调整时可增加 `--set devrelay_client_idle_timeout=3600`，最小值为 `60` 秒。管理服务会监控代理进程和监听端口，异常退出或连续无法监听时自动恢复，最多每 5 分钟尝试 3 次；控制台状态和日志会保留最近一次失败原因。

## 常见问题

### 证书错误

在当前专用浏览器对应的系统证书存储中信任 mitmproxy CA，并完全重启专用浏览器。

### CORS 预检失败

检查规则是否包含 `OPTIONS`，`cors.enabled` 是否为 `true`，`allowOrigin` 是否与前端页面 Origin 完全一致，以及 `allowHeaders` 是否包含浏览器实际声明的请求头。使用凭证时不能把 `allowOrigin` 写成 `*`。

### 代理没有命中规则

检查配置文件是否勾选并保存选择，以及 `host`、`path`、`method` 是否按上一节的实际字符串来写。`host` 只含主机名或 IP；`path` 含查询字符串，前缀要用 `^` 并接住 `/`、`?` 和结尾；跨域预检要包含 `OPTIONS`。本地服务需已启动，且 `target.port` 与它的监听端口一致。

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
