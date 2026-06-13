# CipherPipe 功能补全设计

## 范围

**不做**：前向安全性、密钥轮换、会话过期、群聊、多设备同步、手机 Push (APNs/FCM)、音视频通话

**做**（3批，按依赖排序）：

---

## 第一批：路由发现 + relay 管理

### 1. LAN 发现（mDNS + WS 直连）

proxy.py 启动时：
- 启动 UDP mDNS 监听 (`_cipherpipe._tcp.local.`)，宣告自己的 `IP:8702`
- 同时持续探测局域网同网段 `_cipherpipe._tcp.local.` 广播
- 发现到的 peer 加入 `LAN_PEERS = {pubkey: ip}` 表，超时 60s 无心跳淘汰
- LAN peer 表供路由决策使用，不定时心跳保活

### 2. LAN 直连通道

`lan_handler` 重写：
- 维护 `LAN_CLIENTS = {pubkey: websocket}` 表
- 首次连接时客户端发送 `{"type":"lan_hello","pubkey":"<hex>"}`
- 收到消息后查目标 pubkey 是否在 `LAN_CLIENTS`，在则转发，不在则回 error
- 不是 echo——是多客户端互发的真实路由
- CLI 添加 `--connect-lan <ip>` 参数，指定 LAN peer 地址后直接连 8702

### 3. 自动路由选择

发消息时决策链：
```
if peer in LAN_PEERS and LAN_PEERS[peer]["rtt"] < 50ms:
    → LAN WS 直连
else:
    → Nostr relay 池
```
离线时LAN不可达自动降级，用户无感。

### 4. relay 动态管理

- 启动时读 `~/.cipherpipe/relays.json`，不存在则用默认 3 个
- 连上所有 relay 后发 NIP-11 `["REQ", ...]` 测 RTT，取最低的 5 个做 active pool
- proxy.py 保持到 active pool 的持久连接，其余 idle
- 周期性（每 5 分钟）复查 RTT，动态调整 active pool

### 5. 消息历史拉取

订阅条件改为 `since: <上次会话结束时间或 N 小时前>`。
首次启动拉最近 24h，后续启动从本地记录的最后 event `created_at` 开始。

### 6. 离线消息补齐

- 本地 SQLite 记录 `last_received_at` per peer
- 重连时订阅从该时间戳开始的事件
- relay 端有存的消息全部拉回，按 `created_at` 排序去重后注入消息流

---

## 第二批：身份体验 + 传输能力

### 7. Profile（NIP-01 kind=0）

```json
{"kind": 0, "content": "{\"name\":\"...\",\"about\":\"...\",\"picture\":\"...\",\"nip05\":\"...\"}"}
```
- proxy 启动时自动发布/更新 kind=0
- CLI `--name` 参数生效（之前无效），写入 profile name
- 收到 peer kind=0 时更新本地联系人显示

### 8. 联系人管理

本地 SQLite 表 `contacts`：
```
pubkey TEXT PRIMARY KEY,
petname TEXT,
display_name TEXT,
about TEXT,
picture TEXT,
nip05 TEXT,
last_seen INTEGER,
added_at INTEGER
```
- CLI 新增 `--petname` 参数
- dashboard 支持：添加/删除/编辑别名/搜索
- petname 优先显示，无 petname 显示 truncated pubkey

### 9. 文件传输 — 方案 3 核心

**信号通道**：Nostr kind=4（加密 DM），消息体为 JSON：
```json
{
  "type": "file_offer",
  "file_id": "<uuid>",
  "name": "report.pdf",
  "size": 1048576,
  "mime": "application/pdf",
  "method": "lan_direct",
  "lan_addr": "192.168.0.15:8703",
  "token": "<one-time 256-bit hex>"
}
```
method 为 `lan_direct` 或 `nostr_chunked`。

**LAN 直传**：receiver 收到 offer 后：
1. 如果 method=lan_direct 且 IP 可达，用 token 连 `ws://ip:8703`
2. 双方握手验证 token
3. 流式传输文件内容（分 64KB chunks）
4. 完成后 SHA-256 校验
5. 关闭临时 8703 连接

**Nostr 分块兜底**：
- 文件切成 32KB 块，NIP-44 加密后逐块发 kind=4
- 每块：`{"type":"file_chunk","file_id":"<uuid>","index":0,"total":32,"data":"<base64>"}`
- 最后一块：`{"type":"file_chunk","file_id":"<uuid>","index":31,"total":32,"data":"...","sha256":"<checksum>"}`
- receiver 收齐后组装、校验、落盘

### 10. 文件接收模式

- `--auto-accept` 参数（CLI agent 模式默认开）→ 自动接受，文件落盘到 `./downloads/`
- 浏览器模式 → 弹出确认框（文件名 + 大小），用户点确认后下载
- 同一套逻辑，只是接收端的策略不同

### 11. 结构化数据

消息类型扩展，`content` 不限于纯文本：
```json
{"type":"msg","msg_type":"json","data":{"action":"deploy","target":"prod","commit":"abc123"}}
```
`msg_type` 值：`text` / `json` / `file_offer` / `file_chunk` / `ping` / `read_receipt` / `reaction` / `typing`

### 12. 打字指示器

NIP-45：发送 kind=30450 事件，tags `[["p","<peer>"]]`，content `"typing"`。
收到后 dashboard 显示"对方正在输入..."，3 秒无更新自动消失。

---

## 第三批：消息体验

### 13. 浏览器通知

`Notification API`：`Notification.requestPermission()` 后，收到新消息时弹系统通知。
仅浏览器上下文生效，CLI 不涉及。

### 14. 已读回执

```json
{"type":"read_receipt","event_id":"<nostr event id>","read_at":1234567890}
```
发送方收到后标记消息为已读，dashboard 显示 ✓✓（送达）/ ✓✓ 蓝色（已读）。

### 15. 表情反应

NIP-25：发送 kind=7 事件，tags 含 `[["e","<target event id>"]]`，content 为 emoji。
dashboard 消息下方显示 reaction 列表。

### 16. 消息编辑/删除

编辑：重发同 content、新的 kind=4 事件，tags 加上 `[["e","<original event id>"]]`。客户端用新 content 替换原消息显示，标注"(已编辑)"。

删除：发送 kind=5 事件，tags 含 `[["e","<target event id>"]]`。收到后客户端从视图移除该消息。

### 17. 消息搜索

本地 SQLite FTS5 索引 `messages_fts`：
```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(pubkey, content, timestamp);
```
dashboard 搜索框输入关键词，搜索本地历史，返回匹配消息+跳转到对应位置。

---

## 文件结构

```
cipherpipe/
  proxy.py            # Nostr bridge + LAN router + browser proxy
  cli.py              # Nostr CLI (human/agent)
  dashboard.html      # Browser chat UI
  file_handler.py     # 文件传输协商 + 分块发送/接收
  lan_discovery.py    # mDNS 发现 + LAN peer 表
  relay_manager.py    # relay 配置加载 + RTT 探测 + 动态池
  storage.py          # SQLite 持久化 (contacts, messages, state)
  nostr_crypto.py     # NIP-44 + Schnorr 签名 (从 proxy/cli 抽取公共代码)
  requirements.txt
  run.sh
  nostr.key
```

把 crypto 逻辑从 proxy.py 和 cli.py 各一份拷贝抽取为一个公共模块，消除重复。

---

## 不变的部分

- 加密模型：NIP-44 (ChaCha20Poly1305 + ECDH + HKDF)
- BIP-340 Schnorr 签名
- 浏览器零密钥
- 三层传输骨架（relay 池 / LAN / browser proxy）
- 不依赖自己的服务器，全球 Nostr relay 网络就是路由层
