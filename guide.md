# DevRelay 本地代理使用与配置指南

## 1. 工作原理

```text
专用 Chrome/Edge
  -> 127.0.0.1:8080 (mitmproxy)
  -> 规则匹配、HTTPS 解密、路径重写、请求头处理
  -> localhost:7890 (本地业务服务)
```

`8080` 是默认代理服务端口，`7890` 是本地业务服务端口，两个端口必须不同。代理端口可以在 Web 管理页的“代理控制”中修改；代理运行时需要先停止代理，保存新端口后再启动。

## 2. 安装

需要安装 [uv](https://docs.astral.sh/uv/)。项目使用 Python 3.12。

```bash
cd proxy
uv python install 3.12
uv sync
```

Windows PowerShell 使用相同命令，只需先进入项目的 `proxy` 目录。

首次安装 Python 和依赖需要联网。安装完成后，启动代理和安装本地证书不需要外网。

## 3. 启动步骤

### 3.1 启动本地业务服务

先启动自己的服务，并确认它监听：

```text
http://localhost:7890
```

### 3.2 启动 DevRelay Web 管理服务

推荐使用 Web 管理页启动：

```bash
cd proxy
uv run python devrelay_agent.py
```

它会自动：

- 只启动管理页面，不会自动启动 mitmproxy 代理服务。代理由页面中的“启动代理”按钮或初始化向导启动。
- 打开 `http://127.0.0.1:8787` 管理页面。
- 提供规则编辑、保存、代理启停、日志和浏览器启动按钮。

如果不希望自动打开管理页面：

```bash
uv run python devrelay_agent.py --no-open
```

主界面的“代理配置”区域管理 `configs/` 下的 YAML 文件。可以新建、编辑、重命名、删除、复制和导入文件；勾选文件并调整顺序后点击“保存选择”，启动代理时这些文件会按顺序合并。未选择任何文件时，代理不会启动。

终端里的 Agent 进程结束后，代理子进程会被停止；关闭管理页面本身不会停止代理。

### 3.3 首次初始化向导

第一次打开 `http://127.0.0.1:8787` 时，会自动显示纵向的初始化线路：

```text
环境 -> 代理 -> 证书 -> 完成
```

向导会引导完成：

1. 检查管理服务和当前配置。
2. 启动 mitmproxy 代理。
3. 打开 `http://mitm.it` 并检查 CA 证书是否生成。系统信任证书仍需要在 macOS 或 Windows 中确认一次。
4. 选择代理端口，启动代理。默认是 `8080`，也可以改成其他未被占用的端口。
5. 完成初始化后，按需从主控制台启动 Chrome 或 Edge。浏览器会打开空白页，用户自行输入要访问的目标地址。

完成后进入主控制台。顶部的“初始化向导”按钮可以随时重新打开；完成页的“下次打开时显示初始化向导”开关控制是否在后续启动时自动显示。向导进度保存在本机的 `.devrelay_state.json`，不会写入代理规则。

### 3.4 手动启动 mitmproxy（排错方式）

```bash
cd proxy
uv run mitmdump \
  -p 8080 \
  -s devrelay_proxy.py \
  --set 'devrelay_configs=["configs/default.yml"]'
```

看到下面的日志后保持终端运行：

```text
HTTP(S) proxy listening at *:8080
```

修改 YAML 配置后，代理会在下一次请求时重新读取。修改 Python 代码后必须重启 mitmproxy。

### 3.5 安装 HTTPS 证书

在另一个终端启动专用浏览器：

```bash
uv run python launch_browser.py \
  --browser chrome \
  --profile-dir .profiles \
  --url http://mitm.it
```

`http://mitm.it` 是 mitmproxy 在本机提供的证书页面。

macOS：下载证书，加入“登录”钥匙串，将 `mitmproxy` 证书设置为“始终信任”。

Windows：下载证书，导入“受信任的根证书颁发机构”。

安装后完全退出并重新启动专用浏览器。

### 3.6 启动联调浏览器

```bash
uv run python launch_browser.py \
  --browser chrome \
  --profile-dir .profiles \
  --url about:blank
```

Edge 将 `--browser chrome` 换成 `--browser edge`。

这个浏览器使用独立的 `.profiles/` 数据目录和代理，不会影响日常浏览器的 Cookie、扩展、缓存或系统代理。

## 4. 当前示例映射

当前 [configs/default.yml](./configs/default.yml) 将：

```text
https://api.apifox.com/api/v1/project-categories
```

转发为：

```text
http://localhost:7890/v1/project-categories
```

流程是：匹配域名和路径，删除 `/api` 前缀，改目标主机和端口，再发送给本地服务。

## 5. 配置文件结构

配置文件是 YAML，放在 `configs/` 目录中，根对象必须包含 `rules` 数组。管理页面可以同时勾选多个文件并调整顺序；代理按文件顺序、文件内规则顺序匹配，第一条命中的规则生效。管理页面的表单和高级编辑器都会保存为 YAML。

```yaml
rules:
  - name: api-to-local
    enabled: true
    match:
      host: '^api\.example\.com$'
      path: '^/api(?:/|$)'
      method: '^(GET|POST|PUT|PATCH|DELETE|OPTIONS)$'
    target:
      host: localhost
      port: 9000
    rewritePath:
      pattern: '^/api'
      replacement: ''
    requestHeaders:
      - action: add
        name: X-DevRelay-Local
        value: '1'
      - action: remove
        name: X-Remote-Only
    preserveHost: false
    cors:
      enabled: true
      allowOrigin: 'https://example.com'
      allowCredentials: true
      allowMethods: 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
      allowHeaders: 'Content-Type, Authorization, X-Requested-With'
      maxAge: 600
```

### 5.1 `match`

`host`、`path`、`method` 的值都是 Python 正则表达式。

- `host` 只写域名，不写协议和路径。
- `path` 可以包含查询字符串。
- 前端跨域请求可能先发 `OPTIONS`，需要预检时必须匹配 `OPTIONS`。

### 5.2 `target`

指定本地目标服务。联调统一按 HTTP 连接本地服务，每条规则只配置主机和端口，端口范围是 `1` 到 `65535`。

### 5.3 `rewritePath`

在转发前执行一次正则替换：

```yaml
"rewritePath": {
  "pattern": "^/api",
  "replacement": ""
}
```

`/api/v1/users` 会变成 `/v1/users`。

### 5.4 请求头和响应头

`requestHeaders` 和 `responseHeaders` 都使用操作列表：
规则先按域名、路径和方法命中，命中后才执行这些 Header 操作。

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

`add` 会追加同名 Header，`set` 会覆盖已有值，`remove` 删除 Header。

Header 值支持 `$origin`、`$host`、`$path`、`$query`、`$method` 等内置变量，也支持命名捕获变量。

### 5.5 命名捕获变量

```yaml
match:
  path: '^/users/(?P<userId>[^/]+)$'
responseHeaders:
  - action: set
    name: X-User-Id
    value: '${userId}'
```

请求 `/users/42` 时，`${userId}` 的值就是 `42`。这是 Python 正则的命名捕获语法。

### 5.6 `preserveHost`

```yaml
"preserveHost": false
```

为 `false` 时本地服务收到 `Host: localhost:端口`，适合普通本地服务。为 `true` 时保留原始域名，例如 `Host: api.example.com`。

## 6. CORS 配置

### 6.1 开关

启用：

```yaml
"cors": {
  "enabled": true
}
```

启用后，代理会为实际响应增加 CORS 响应头，并直接处理 `OPTIONS` 预检请求，返回 `204`。响应体不会被修改。

关闭：

```yaml
"cors": {
  "enabled": false
}
```

也可以删除整个 `cors` 字段。

### 6.2 CORS 字段

```yaml
"cors": {
  "enabled": true,
  "allowOrigin": "https://apifox.com",
  "allowCredentials": true,
  "allowMethods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "allowHeaders": "Content-Type, Authorization, X-Requested-With",
  "maxAge": 600
}
```

- `allowOrigin`：前端页面的 Origin，例如 `https://apifox.com`。不要写接口域名，也不要带路径。
- `allowCredentials`：是否允许 Cookie 等凭证。需要凭证时必须写具体 Origin。
- `allowMethods`：允许的 HTTP 方法，通常包含 `OPTIONS`。
- `allowHeaders`：允许前端携带的请求头。代理会优先回显浏览器预检请求中实际声明的请求头。
- `maxAge`：预检结果缓存秒数。

如果不需要 Cookie，可以允许任意来源：

```yaml
"allowOrigin": "*",
"allowCredentials": false
```

不能同时使用：

```http
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
```

浏览器会拒绝这种组合。

如果页面是 `https://apifox.com:3000`，Origin 也必须写成 `https://apifox.com:3000`。

## 7. 支持范围

- HTTP 和 HTTPS 请求。
- WebSocket：`ws` 和 `wss`。
- SSE（Server-Sent Events）和其他 HTTP 长连接。
- 文件上传、普通请求体和请求头。
- 请求头增加、覆盖和删除。
- 按域名、路径和方法匹配。
- 请求路径正则重写。
- CORS 响应头和 `OPTIONS` 预检处理。

当前不修改响应体，也不会自动启动你的本地业务服务。

## 8. 日志和排错

匹配成功时会看到：

```text
route api-to-local POST -> http://localhost:9000/v1/users
```

没有 `route` 日志时，检查：

1. `host` 是否只写域名。
2. `path` 正则是否匹配实际路径。
3. `method` 是否包含实际方法，尤其是 `OPTIONS`。
4. 本地服务端口是否正确且已启动。
5. `8080` 代理端口和本地业务端口是否写反。

常见错误：

- `NET::ERR_CERT_AUTHORITY_INVALID`：没有信任 mitmproxy CA，或安装证书后没有重启专用浏览器。
- CORS 错误：检查 `cors.enabled`、`allowOrigin` 是否与前端页面 Origin 完全一致。
- 本地 Host 不对：普通服务使用 `preserveHost: false`。

## 9. 测试

```bash
uv run python -m unittest discover -s tests -v
```
