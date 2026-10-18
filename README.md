# DevRelay 本地代理配置手册

完整的安装、启动和配置说明请看 [guide.md](./guide.md)。

这个目录是 DevRelay 的本地代理原型。它使用 mitmproxy 接收 Chrome/Edge 的 HTTP、HTTPS、WebSocket 和长连接请求，按规则把指定请求转发到本地服务。

典型链路：

```text
专用 Chrome/Edge
  -> 127.0.0.1:8080 (mitmproxy)
  -> 规则匹配、HTTPS 解密、路径重写、请求头处理
  -> localhost:7890 (你的本地业务服务)
```

代理端口和业务服务端口必须不同。下面示例使用 `8080` 作为代理端口，`7890` 作为本地业务端口。

## 一、安装

需要安装 [uv](https://docs.astral.sh/uv/)。项目使用 Python 3.12，uv 会负责创建虚拟环境和安装依赖。

macOS/Linux：

```bash
cd proxy
uv python install 3.12
uv sync
```

Windows PowerShell：

```powershell
cd <项目目录>\proxy
uv python install 3.12
uv sync
```

首次执行 `uv python install` 和 `uv sync` 需要下载 Python 或依赖。安装完成后，启动代理和安装证书不需要外网。

## 二、第一次启动

### 1. 启动本地业务服务

先确保你的业务服务已经监听目标地址，例如：

```text
http://localhost:7890
```

### 2. 配置规则

编辑 [configs/default.yml](./configs/default.yml)。当前示例将：

```text
https://api.apifox.com/api/v1/project-categories
```

转发为：

```text
http://localhost:7890/v1/project-categories
```

### 3. 启动 DevRelay Web 管理服务

推荐直接启动本地管理页：

```bash
uv run python devrelay_agent.py
```

它只会打开 `http://127.0.0.1:8787` 管理页面，不会自动启动代理。代理由页面中的按钮或初始化向导启动。页面可以管理多个 YAML 配置文件、用表单或 YAML 编辑规则、启停代理、查看日志和启动专用浏览器。

### 4. 手动启动 mitmproxy（排错方式）

在第一个终端执行：

```bash
cd proxy
uv run mitmdump \
  -p 8080 \
  -s devrelay_proxy.py \
  --set 'devrelay_configs=["configs/default.yml"]'
```

看到 `HTTP(S) proxy listening at *:8080` 后，保持这个终端运行。

配置文件保存后，代理会在下一次请求时自动重新加载；修改 Python 代码后必须重启 mitmproxy。

## 三、安装 HTTPS 证书

HTTPS 请求需要 mitmproxy 的本地 CA 证书。证书页面由 mitmproxy 在本机提供，不需要访问外网。

### macOS

在第二个终端启动专用 Chrome：

```bash
cd proxy
uv run python launch_browser.py \
  --browser chrome \
  --profile-dir .profiles \
  --url http://mitm.it
```

在页面中下载 macOS 证书，然后：

1. 双击下载的证书，打开“钥匙串访问”。
2. 将证书加入“登录”钥匙串。
3. 找到 `mitmproxy` 证书并双击。
4. 展开“信任”，将“使用此证书时”设为“始终信任”。
5. 输入 macOS 登录密码确认。

### Windows

使用同样的启动命令，把 `--browser chrome` 换成 `--browser edge` 也可以。按照 `http://mitm.it` 页面提示下载证书，并导入 Windows 的“受信任的根证书颁发机构”。

证书安装后，关闭并重新启动专用浏览器。

## 四、启动专用浏览器

```bash
cd proxy
uv run python launch_browser.py \
  --browser chrome \
  --profile-dir .profiles \
  --url https://你的前端测试页面
```

Edge：

```bash
uv run python launch_browser.py \
  --browser edge \
  --profile-dir .profiles \
  --url https://你的前端测试页面
```

启动器会使用已安装的 Chrome/Edge，并传入：

- `--user-data-dir`：独立浏览器数据目录，不使用日常浏览器的 Cookie、缓存和扩展。
- `--proxy-server`：将该浏览器的 HTTP/HTTPS 请求交给 `127.0.0.1:8080`。
- `--url`：启动时打开的初始页面。

默认目录是当前 `proxy` 目录下的 `.profiles/`。它不会修改日常浏览器或系统代理。

## 五、完整配置格式

每个 `configs/*.yml` 文件的根对象包含 `rules` 数组。管理页面可以同时勾选多个文件并调整顺序；代理会按文件顺序、文件内规则顺序匹配，第一条命中的规则生效。

管理页面支持新建、编辑、重命名、删除、复制和导入配置文件。启动代理前勾选要生效的文件并调整顺序；没有选中任何文件时，启动会被阻止。

```yaml
rules:
  - name: apifox-project-categories-to-local
    enabled: true
    match:
      host: '^api\.apifox\.com$'
      path: '^/api/v1/project-categories(?:$|\?)'
      method: '^(GET|POST|PUT|PATCH|DELETE|OPTIONS)$'
    target:
      host: localhost
      port: 7890
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
      allowOrigin: 'https://apifox.com'
      allowCredentials: true
      allowMethods: 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
      allowHeaders: 'Content-Type, Authorization, X-Requested-With'
      maxAge: 600
```

### `name`

规则名称，只用于日志识别。

### `enabled`

规则开关。设为 `false` 后跳过这条规则：

```yaml
"enabled": true
```

### `match.host`

匹配请求域名，使用 Python 正则表达式。请求 URL 中的协议和路径不写在这里。

```yaml
"host": "^api\\.apifox\\.com$"
```

### `match.path`

匹配请求路径，也使用 Python 正则表达式。当前值可能包含查询字符串：

```yaml
"path": "^/api/v1/project-categories(?:$|\\?)"
```

### `match.method`

匹配 HTTP 方法。跨域请求可能先使用 `OPTIONS` 预检，因此需要代理预检时必须把 `OPTIONS` 放进正则。

### `target`

目标本地服务地址。协议由主界面的“本地服务协议”全局设置统一控制，默认是 `http`；每条规则只配置主机和端口：

```yaml
"target": {
  "host": "localhost",
  "port": 7890
}
```

端口必须在 `1` 到 `65535` 之间。

### `rewritePath`

在转发前重写路径，只执行一次替换：

```yaml
"rewritePath": {
  "pattern": "^/api",
  "replacement": ""
}
```

效果：`/api/v1/project-categories` 会变成 `/v1/project-categories`。

### 请求头和响应头

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

- `add`：追加 Header，同名 Header 可以出现多次。
- `set`：覆盖已有 Header。
- `remove`：删除 Header，不需要填写 `value`。

Header 值支持 `$origin`、`$host`、`$path`、`$query`、`$method` 等内置变量，也支持命名捕获变量。

### 命名捕获变量

匹配正则使用 Python 命名捕获语法：

```yaml
match:
  path: '^/users/(?P<userId>[^/]+)$'
responseHeaders:
  - action: set
    name: X-User-Id
    value: '${userId}'
```

请求 `/users/42` 时，`${userId}` 的值就是 `42`。命名捕获可以写在 `host`、`path` 或 `method` 正则中。

### `preserveHost`

控制转发给本地服务的 `Host` 请求头。

设置为 `false` 时，本地服务收到：

```http
Host: localhost:7890
```

适合普通本地服务。设置为 `true` 时，本地服务收到原始域名，例如：

```http
Host: api.apifox.com
```

### `cors`

`cors.enabled` 是跨域处理开关：

```yaml
"cors": {
  "enabled": true
}
```

启用后，代理会为匹配规则的响应增加 CORS 响应头，直接处理 `OPTIONS` 预检请求并返回 `204`，但不会修改响应体。

关闭方式：

```yaml
"cors": {
  "enabled": false
}
```

或者直接删除 `cors` 字段。

#### `allowOrigin`

允许哪个前端来源访问：

```yaml
"allowOrigin": "https://apifox.com"
```

它必须是前端页面的 Origin，不是接口地址，也不包含路径：

```text
正确： https://apifox.com
错误： https://api.apifox.com
错误： https://apifox.com/index.html
```

也可以使用：

```yaml
"allowOrigin": "$origin"
```

让代理回显请求中的 `Origin`。只建议在本地调试使用。

#### `allowCredentials`

```yaml
"allowCredentials": true
```

允许跨域请求携带 Cookie 等凭证。如果接口不需要登录 Cookie，可以设为 `false`。

当它为 `true` 时，`allowOrigin` 不能写 `*`，必须写具体来源：

```yaml
"allowOrigin": "https://apifox.com",
"allowCredentials": true
```

如果不需要凭证，可以允许任意来源：

```yaml
"allowOrigin": "*",
"allowCredentials": false
```

#### `allowMethods`

允许跨域使用的 HTTP 方法：

```yaml
"allowMethods": "GET, POST, PUT, PATCH, DELETE, OPTIONS"
```

其中 `OPTIONS` 是浏览器的 CORS 预检方法。

#### `allowHeaders`

允许跨域请求携带的请求头：

```yaml
"allowHeaders": "Content-Type, Authorization, X-Requested-With"
```

常见用途：`Content-Type` 用于 JSON，`Authorization` 用于 token，`X-Requested-With` 由部分 AJAX 库使用。浏览器预检请求带有 `Access-Control-Request-Headers` 时，代理会优先回显浏览器实际请求的请求头。

#### `maxAge`

预检结果缓存时间，单位是秒：

```yaml
"maxAge": 600
```

## 六、请求转发示例

### 不改路径

```text
https://api.example.com/user/list
    -> http://localhost:9000/user/list
```

### 删除路径前缀

```text
https://api.apifox.com/api/v1/project-categories
    -> http://localhost:7890/v1/project-categories
```

### WebSocket 和文件上传

WebSocket（`ws` / `wss`）、SSE、文件上传、长连接和请求体会随匹配请求一起转发，不需要额外配置。当前版本只修改请求和响应头，不修改响应体。

## 七、验证和日志

匹配成功时，mitmproxy 终端会输出类似：

```text
route apifox-project-categories-to-local POST -> http://localhost:7890/v1/project-categories
```

如果没有 `route` 日志，说明域名、路径或方法没有命中规则。

运行规则单元测试：

```bash
uv run python -m unittest discover -s tests -v
```

## 八、常见问题

### `NET::ERR_CERT_AUTHORITY_INVALID`

没有信任 mitmproxy CA，或证书安装后没有重启专用浏览器。重新打开 `http://mitm.it` 安装证书，并完全退出后重启浏览器。

### 请求没有转到本地

检查：

1. `host` 是否只写域名，不带协议。
2. `path` 正则是否匹配实际路径。
3. `method` 是否包含实际方法，尤其是 `OPTIONS`。
4. 本地服务是否监听配置中的目标端口。
5. 代理端口 `8080` 和业务端口 `7890` 是否写反。

### CORS 错误

确认规则中存在：

```yaml
"cors": {
  "enabled": true,
  "allowOrigin": "https://apifox.com"
}
```

如果前端页面有端口，Origin 也必须带端口，例如 `https://apifox.com:3000`。修改 `devrelay_proxy.py` 后必须重启 mitmproxy；只改 YAML 时下一次请求会自动加载。

### 本地服务收到了错误的 Host

普通本地服务使用：

```yaml
"preserveHost": false
```

只有本地服务需要按测试环境域名做虚拟主机路由时，才使用 `true`。

### 未命中的请求会怎样

未命中的请求不会被改写，会由 mitmproxy 按原地址正常转发。

## 九、当前限制

- 当前是命令行原型，没有桌面配置界面。
- 规则修改通过 YAML 文件或管理页面表单完成。
- 响应体不会被改写。
- HTTPS 解密需要在使用的系统中信任 mitmproxy CA。
- 浏览器启动器只负责启动 Chrome/Edge 和设置代理，不会启动你的业务服务。
