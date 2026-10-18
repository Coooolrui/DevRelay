# Poseidon 本地代理使用与配置指南

## 1. 工作原理

```text
专用 Chrome/Edge
  -> 127.0.0.1:8080 (mitmproxy)
  -> 规则匹配、HTTPS 解密、路径重写、请求头处理
  -> localhost:7890 (本地业务服务)
```

`8080` 是代理服务端口，`7890` 是本地业务服务端口，两个端口必须不同。

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

### 3.2 启动 mitmproxy

```bash
cd proxy
uv run mitmdump \
  -p 8080 \
  -s poseidon_proxy.py \
  --set poseidon_config=proxy_config.json
```

看到下面的日志后保持终端运行：

```text
HTTP(S) proxy listening at *:8080
```

修改 JSON 配置后，代理会在下一次请求时重新读取。修改 Python 代码后必须重启 mitmproxy。

### 3.3 安装 HTTPS 证书

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

### 3.4 启动联调浏览器

```bash
uv run python launch_browser.py \
  --browser chrome \
  --profile-dir .profiles \
  --url https://你的前端测试页面
```

Edge 将 `--browser chrome` 换成 `--browser edge`。

这个浏览器使用独立的 `.profiles/` 数据目录和代理，不会影响日常浏览器的 Cookie、扩展、缓存或系统代理。

## 4. 当前示例映射

当前 [proxy_config.json](./proxy_config.json) 将：

```text
https://api.apifox.com/api/v1/project-categories
```

转发为：

```text
http://localhost:7890/v1/project-categories
```

流程是：匹配域名和路径，删除 `/api` 前缀，改目标主机和端口，再发送给本地服务。

## 5. 配置文件结构

配置文件是 JSON，根对象必须包含 `rules` 数组。规则按顺序匹配，第一条命中的规则生效。

```json
{
  "rules": [
    {
      "name": "api-to-local",
      "enabled": true,
      "match": {
        "host": "^api\\.example\\.com$",
        "path": "^/api(?:/|$)",
        "method": "^(GET|POST|PUT|PATCH|DELETE|OPTIONS)$",
        "headers": {
          "X-Environment": "^test$"
        }
      },
      "target": {
        "scheme": "http",
        "host": "localhost",
        "port": 9000
      },
      "rewritePath": {
        "pattern": "^/api",
        "replacement": ""
      },
      "requestHeaders": {
        "X-Poseidon-Local": "1"
      },
      "removeRequestHeaders": ["X-Remote-Only"],
      "preserveHost": false,
      "cors": {
        "enabled": true,
        "allowOrigin": "https://example.com",
        "allowCredentials": true,
        "allowMethods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "allowHeaders": "Content-Type, Authorization, X-Requested-With",
        "maxAge": 600
      }
    }
  ]
}
```

### 5.1 `match`

`host`、`path`、`method` 和 `headers` 的值都是 Python 正则表达式。

- `host` 只写域名，不写协议和路径。
- `path` 可以包含查询字符串。
- 前端跨域请求可能先发 `OPTIONS`，需要预检时必须匹配 `OPTIONS`。
- `headers` 的名称不区分大小写，值按正则匹配。

### 5.2 `target`

指定本地目标服务。`scheme` 支持 `http` 和 `https`，端口范围是 `1` 到 `65535`。

### 5.3 `rewritePath`

在转发前执行一次正则替换：

```json
"rewritePath": {
  "pattern": "^/api",
  "replacement": ""
}
```

`/api/v1/users` 会变成 `/v1/users`。

### 5.4 请求头

增加或覆盖请求头：

```json
"requestHeaders": {
  "Authorization": "Bearer local-token"
}
```

删除请求头：

```json
"removeRequestHeaders": ["X-Remote-Only"]
```

### 5.5 `preserveHost`

```json
"preserveHost": false
```

为 `false` 时本地服务收到 `Host: localhost:端口`，适合普通本地服务。为 `true` 时保留原始域名，例如 `Host: api.example.com`。

## 6. CORS 配置

### 6.1 开关

启用：

```json
"cors": {
  "enabled": true
}
```

启用后，代理会为实际响应增加 CORS 响应头，并直接处理 `OPTIONS` 预检请求，返回 `204`。响应体不会被修改。

关闭：

```json
"cors": {
  "enabled": false
}
```

也可以删除整个 `cors` 字段。

### 6.2 CORS 字段

```json
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

```json
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
- WebSocket。
- 文件上传和普通请求体。
- 请求头增加、覆盖和删除。
- 按域名、路径、方法、请求头正则匹配。
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
