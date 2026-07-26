<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CipherPipe</title>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --bg: #f6f7f9; --bg2: #ffffff; --bg3: #f0f1f4; --border: #e4e6eb;
  --text: #1c1e21; --text2: #8a8d91; --primary: #4f7cff; --primary2: #3b63e0;
  --msg-in: #ffffff; --msg-out: linear-gradient(135deg,#4f7cff,#3b63e0);
  --hover: #eceef1; --danger: #e5484d; --success: #30a46c;
  --shadow: 0 1px 2px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.06);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.05);
  --radius: 14px;
}
body.dark {
  --bg: #0e1013; --bg2: #16191f; --bg3: #1c2027; --border: #2a2f38;
  --text: #e7e9ec; --text2: #7d828c; --primary: #6b8cff; --primary2: #4f7cff;
  --msg-in: #1c2027; --msg-out: linear-gradient(135deg,#4f7cff,#3b63e0);
  --hover: #22262e; --danger: #f2555a; --success: #3dd68c;
  --shadow: 0 1px 2px rgba(0,0,0,.3), 0 4px 16px rgba(0,0,0,.3);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.25);
}
body { background:var(--bg); color:var(--text); font:14px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",sans-serif; height:100vh; -webkit-font-smoothing:antialiased; }
#app { display:flex; height:100vh; }

/* ── Sidebar ── */
.sidebar { width:280px; background:var(--bg2); border-right:1px solid var(--border); display:flex; flex-direction:column; flex-shrink:0; }
.brand { padding:20px 20px 14px; display:flex; align-items:center; gap:10px; cursor:pointer; }
.brand-logo { width:34px; height:34px; border-radius:10px; background:linear-gradient(135deg,#4f7cff,#3b63e0); display:flex; align-items:center; justify-content:center; color:#fff; font-size:17px; font-weight:700; box-shadow:0 4px 12px rgba(79,124,255,.35); }
.brand-name { font-size:17px; font-weight:700; letter-spacing:-.3px; }
.brand-tag { font-size:10px; color:var(--text2); margin-top:-2px; }
.sidebar-actions { padding:0 16px 10px; }
.sidebar-actions button { width:100%; padding:9px; border:1px solid var(--border); border-radius:10px; background:var(--bg3); color:var(--text); font-size:12px; font-weight:600; cursor:pointer; transition:all .15s; }
.sidebar-actions button:hover { background:var(--hover); transform:translateY(-1px); }
.identity { margin:0 16px 12px; padding:12px; background:var(--bg3); border-radius:12px; }
.identity-label { font-size:10px; color:var(--text2); text-transform:uppercase; letter-spacing:.6px; margin-bottom:5px; font-weight:600; }
.identity-pk { font-size:10.5px; font-family:"SF Mono",Menlo,monospace; word-break:break-all; color:var(--text); line-height:1.5; opacity:.85; }
.identity-actions { margin-top:8px; display:flex; gap:12px; }
.identity-actions a { font-size:11px; color:var(--primary); cursor:pointer; font-weight:600; text-decoration:none; }
.identity-actions a:hover { text-decoration:underline; }
.identity-actions a.danger { color:var(--danger); }
.search-wrap { padding:0 16px 10px; position:relative; }
.search { width:100%; padding:9px 12px 9px 32px; border-radius:10px; border:1px solid var(--border); background:var(--bg3); color:var(--text); font-size:12.5px; font-family:inherit; transition:all .15s; }
.search:focus { outline:none; border-color:var(--primary); background:var(--bg2); box-shadow:0 0 0 3px rgba(79,124,255,.15); }
.search-icon { position:absolute; left:28px; top:50%; transform:translateY(-50%); margin-top:-5px; color:var(--text2); font-size:13px; pointer-events:none; }
.peers { flex:1; overflow-y:auto; padding:4px 10px; }
.peers::-webkit-scrollbar { width:5px; }
.peers::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }
.peer { padding:10px 12px; border-radius:12px; cursor:pointer; display:flex; align-items:center; gap:11px; transition:background .12s; margin-bottom:2px; }
.peer:hover { background:var(--hover); }
.peer.active { background:rgba(79,124,255,.1); }
.avatar { width:38px; height:38px; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center; color:#fff; font-size:13px; font-weight:700; }
.peer-info { flex:1; min-width:0; }
.peer .name { font-weight:600; font-size:13.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.peer .pk { color:var(--text2); font-size:10.5px; font-family:"SF Mono",Menlo,monospace; }
.badge { min-width:19px; height:19px; padding:0 5px; border-radius:10px; background:var(--danger); color:#fff; font-size:10.5px; font-weight:700; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.peer .del { color:var(--text2); opacity:0; cursor:pointer; font-size:15px; padding:4px; border-radius:6px; transition:all .12s; }
.peer:hover .del { opacity:1; }
.peer .del:hover { color:var(--danger); background:var(--bg3); }
.add-btn { margin:10px 16px 16px; padding:11px 0; background:linear-gradient(135deg,#4f7cff,#3b63e0); border:none; color:#fff; border-radius:12px; cursor:pointer; font-size:13px; font-weight:600; text-align:center; transition:all .15s; box-shadow:0 4px 12px rgba(79,124,255,.3); }
.add-btn:hover { transform:translateY(-1px); box-shadow:0 6px 16px rgba(79,124,255,.4); }

/* ── Main ── */
.main { flex:1; display:flex; flex-direction:column; min-width:0; }
.header { padding:14px 24px; border-bottom:1px solid var(--border); background:var(--bg2); display:flex; align-items:center; gap:12px; flex-shrink:0; }
.header-avatar { width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; color:#fff; font-size:13px; font-weight:700; }
.header .title { font-weight:700; font-size:15px; }
.header .subtitle { font-size:11px; color:var(--text2); }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:5px; }
.dot.on { background:var(--success); box-shadow:0 0 6px var(--success); }
.dot.off { background:var(--text2); }
.header .status { font-size:11.5px; color:var(--text2); display:flex; align-items:center; }
.theme-toggle { cursor:pointer; font-size:11.5px; color:var(--text2); user-select:none; padding:6px 12px; border-radius:8px; border:1px solid var(--border); transition:all .15s; font-weight:600; }
.theme-toggle:hover { color:var(--primary); border-color:var(--primary); }
.typing { font-size:11.5px; color:var(--primary); padding:6px 24px; height:28px; flex-shrink:0; font-style:italic; }

/* ── Messages ── */
.msgs { flex:1; overflow-y:auto; padding:20px 24px; display:flex; flex-direction:column; gap:10px; }
.msgs::-webkit-scrollbar { width:5px; }
.msgs::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }
.msg-row { display:flex; gap:9px; animation:slideUp .18s ease-out; }
@keyframes slideUp { from{opacity:0; transform:translateY(6px)} to{opacity:1; transform:translateY(0)} }
.msg-row.out { flex-direction:row-reverse; }
.msg-avatar { width:30px; height:30px; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center; color:#fff; font-size:11px; font-weight:700; margin-top:2px; }
.msg { max-width:62%; padding:10px 14px; border-radius:16px; font-size:13.5px; position:relative; box-shadow:var(--shadow-sm); }
.msg-row.in .msg { background:var(--msg-in); border:1px solid var(--border); border-bottom-left-radius:5px; }
.msg-row.out .msg { background:var(--msg-out); color:#fff; border-bottom-right-radius:5px; }
.msg .meta { font-size:10px; margin-bottom:3px; display:flex; justify-content:space-between; gap:10px; opacity:.65; }
.msg .body { word-break:break-word; white-space:pre-wrap; }
.msg .rx { font-size:14px; margin-top:4px; }
.msg .actions { display:none; position:absolute; top:-16px; right:0; background:var(--bg2); border:1px solid var(--border); border-radius:10px; padding:2px 4px; box-shadow:var(--shadow); z-index:5; }
.msg:hover .actions { display:flex; gap:2px; }
.actions button { background:none; border:none; font-size:13px; cursor:pointer; padding:3px 5px; border-radius:6px; transition:background .1s; }
.actions button:hover { background:var(--hover); }
.tick { font-size:10px; }
.tick.read { color:#7ec8ff; }

/* ── Empty state ── */
.empty { margin:auto; text-align:center; color:var(--text2); }
.empty-icon { width:72px; height:72px; margin:0 auto 18px; border-radius:22px; background:linear-gradient(135deg,#4f7cff22,#3b63e011); display:flex; align-items:center; justify-content:center; font-size:32px; }
.empty h3 { color:var(--text); font-size:17px; margin-bottom:8px; font-weight:700; }
.empty p { font-size:12.5px; line-height:1.8; max-width:340px; }
.empty .lock { color:var(--success); }

/* ── Input bar ── */
.input-bar { padding:14px 24px 18px; background:var(--bg2); border-top:1px solid var(--border); display:flex; gap:10px; align-items:center; flex-shrink:0; }
.input-bar input { flex:1; padding:12px 16px; border-radius:24px; border:1px solid var(--border); background:var(--bg3); color:var(--text); font-family:inherit; font-size:13.5px; transition:all .15s; }
.input-bar input:focus { outline:none; border-color:var(--primary); background:var(--bg2); box-shadow:0 0 0 3px rgba(79,124,255,.15); }
.icon-btn { width:42px; height:42px; border-radius:50%; border:none; cursor:pointer; font-size:17px; display:flex; align-items:center; justify-content:center; transition:all .15s; flex-shrink:0; }
.btn-file { background:var(--bg3); color:var(--text2); border:1px solid var(--border); }
.btn-file:hover { color:var(--primary); border-color:var(--primary); transform:translateY(-1px); }
.btn-send { background:linear-gradient(135deg,#4f7cff,#3b63e0); color:#fff; box-shadow:0 4px 12px rgba(79,124,255,.35); }
.btn-send:hover { transform:translateY(-1px) scale(1.04); box-shadow:0 6px 16px rgba(79,124,255,.45); }

/* ── Progress ── */
.progress-bar { margin-top:7px; height:16px; background:rgba(0,0,0,.12); border-radius:8px; overflow:hidden; position:relative; }
.progress-fill { height:100%; background:linear-gradient(90deg,#4f7cff,#6b8cff); border-radius:8px; transition:width .15s; }
.progress-bar span { position:absolute; top:0; left:0; width:100%; text-align:center; font-size:10px; line-height:16px; color:#fff; font-weight:600; }
</style>
</head>
<body>
<div id="app">
  <div class="sidebar">
    <div class="brand" @click="currentPeer=null;messages=[]">
      <div class="brand-logo">C</div>
      <div>
        <div class="brand-name">CipherPipe</div>
        <div class="brand-tag">端到端加密管道</div>
      </div>
    </div>
    <div class="sidebar-actions" v-if="!myPubkey">
      <button @click="createIdentity">创建身份</button>
    </div>
    <div class="identity" v-if="myPubkey">
      <div class="identity-label">我的公钥</div>
      <div class="identity-pk">{{ myPubkey.slice(0,20) }}...{{ myPubkey.slice(-8) }}</div>
      <div class="identity-actions">
        <a @click.prevent="copyPubkey">{{ copied ? '已复制 ✓' : '复制完整公钥' }}</a>
        <a class="danger" @click.prevent="createIdentity">重新生成</a>
      </div>
    </div>
    <div class="search-wrap">
      <span class="search-icon">⌕</span>
      <input class="search" v-model="searchQuery" placeholder="搜索消息..." @input="search">
    </div>
    <div class="peers">
      <div v-for="p in peers" :key="p.pubkey"
           :class="['peer', {active: currentPeer === p.pubkey}]"
           @click="switchPeer(p.pubkey)">
        <div class="avatar" :style="{background: avatarColor(p.pubkey)}">{{ (p.petname || p.pubkey).slice(0,1).toUpperCase() }}</div>
        <div class="peer-info">
          <div class="name">{{ p.petname || p.pubkey.slice(0,12)+'...' }}</div>
          <div class="pk">{{ p.lastMsg || p.pubkey.slice(0,10)+'...' }}</div>
        </div>
        <span v-if="p.unread" class="badge">{{ p.unread > 99 ? '99+' : p.unread }}</span>
        <span class="del" @click.stop="delPeer(p.pubkey)">✕</span>
      </div>
    </div>
    <div class="add-btn" @click="addPeer">+ 添加联系人</div>
  </div>

  <div class="main">
    <div class="header">
      <template v-if="currentPeer">
        <div class="header-avatar" :style="{background: avatarColor(currentPeer)}">{{ chatTitle.slice(0,1).toUpperCase() }}</div>
        <div>
          <div class="title">{{ chatTitle }}</div>
          <div class="subtitle">{{ currentPeer.slice(0,16) }}...</div>
        </div>
      </template>
      <template v-else>
        <div class="title">CipherPipe</div>
      </template>
      <span style="flex:1"></span>
      <span v-if="currentPeer" class="status">
        <span :class="['dot', peerOnline ? 'on' : 'off']"></span>{{ peerOnline ? '在线' : '离线' }}
      </span>
      <span class="theme-toggle" @click="toggleTheme">{{ dark ? '☀ 日间' : '☾ 夜间' }}</span>
    </div>
    <div class="typing">{{ typingText }}</div>
    <div class="msgs" ref="msgContainer">
      <div v-if="!currentPeer" class="empty">
        <div class="empty-icon">🔐</div>
        <h3>安全通信，从添加联系人开始</h3>
        <p><span class="lock">🔒</span> 端到端加密 · 去中心化<br>数据通过全球 Nostr relay 网络传输<br>不经过任何中心服务器</p>
      </div>
      <div v-for="m in messages" :key="m.id" :class="['msg-row', m.dir]">
        <div class="msg-avatar" :style="{background: avatarColor(m.dir === 'out' ? myPubkey : (m.from||'?'))}">{{ (m.dir === 'out' ? 'me' : (m.from||'?')).slice(0,1).toUpperCase() }}</div>
        <div :class="['msg']"
             @mouseenter="m.hover=true" @mouseleave="m.hover=false">
          <div v-if="m.hover" class="actions">
            <button @click="react(m, '👍')">👍</button>
            <button @click="react(m, '❤️')">❤️</button>
            <button @click="react(m, '😂')">😂</button>
            <button @click="react(m, '🔥')">🔥</button>
            <button @click="delMsg(m)">✕</button>
          </div>
          <div class="meta">
            <span>{{ m.dir === 'out' ? 'me' : m.from }}</span>
            <span v-if="m.dir==='out'" :class="['tick', {read: m.delivered}]">✓✓</span>
          </div>
          <div class="body">{{ m.text }}</div>
          <div v-if="m.progress != null" class="progress-bar"><div class="progress-fill" :style="{width: m.progress+'%'}"></div><span>{{ m.progress }}%</span></div>
          <div v-if="m.reactions" class="rx">{{ m.reactions }}</div>
        </div>
      </div>
    </div>
    <div v-if="currentPeer" class="input-bar">
      <button class="icon-btn btn-file" @click="sendFile" title="发送文件">📎</button>
      <input v-model="inputText" placeholder="输入消息..."
             @keydown.enter="send" @input="onTyping">
      <button class="icon-btn btn-send" @click="send" title="发送">➤</button>
    </div>
  </div>
</div>

<script>
const { createApp, ref, computed, nextTick, watch, onMounted } = Vue;

createApp({
  setup() {
    const ws = ref(null);
    const currentPeer = ref(null);
    const myPubkey = ref(localStorage.getItem('cp_my_pubkey') || '');
    const copied = ref(false);
    const peers = ref(JSON.parse(localStorage.getItem('cp_peers') || '[]').map(p => typeof p === 'string' ? {pubkey:p, petname:''} : p));
    const messages = ref([]);
    const inputText = ref('');
    const searchQuery = ref('');
    const statusText = ref('disconnected');
    const statusClass = ref('off');
    const peerOnline = ref(false);
    const typingText = ref('');
    const msgContainer = ref(null);
    let typingTimeout = null;
    let msgId = 0;
    let savedMessages = [];
    let isSearching = false;

    const AVATAR_COLORS = ['#4f7cff','#9b59d0','#e5484d','#30a46c','#e8930c','#0ca6a6','#d6336c','#5c7cfa'];
    function avatarColor(key) {
      let h = 0;
      for (const c of (key || '?')) h = (h * 31 + c.charCodeAt(0)) >>> 0;
      return AVATAR_COLORS[h % AVATAR_COLORS.length];
    }

    const dark = ref(localStorage.getItem('cp_dark') === '1');
    const themeLabel = computed(() => dark.value ? '日间模式' : '夜间模式');
    function toggleTheme() {
      dark.value = !dark.value;
      localStorage.setItem('cp_dark', dark.value ? '1' : '0');
      document.body.classList.toggle('dark', dark.value);
    }
    if (dark.value) document.body.classList.add('dark');

    const chatTitle = computed(() => {
      if (!currentPeer.value) return '首页';
      const p = peers.value.find(x => x.pubkey === currentPeer.value);
      return p && p.petname ? p.petname : currentPeer.value.slice(0,12) + '...';
    });
    const isChatOpen = computed(() => !!currentPeer.value);

    function connect() {
      if (ws.value) ws.value.close();
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws.value = new WebSocket(`${proto}//${location.host}/ws`);
      ws.value.onopen = () => {
        statusText.value = 'connected';
        statusClass.value = 'on';
        if (Notification.permission === 'default') Notification.requestPermission();
      };
      ws.value.onclose = () => {
        statusText.value = 'disconnected';
        statusClass.value = 'off';
        setTimeout(connect, 3000);
      };
      ws.value.onmessage = (e) => {
        // Binary frame = incoming file chunk
        if (e.data instanceof Blob) {
          const lastFile = [...messages.value].reverse().find(x => x.dir === 'in' && x.progress != null && x._fchunks);
          if (lastFile && lastFile._fchunks > 0) {
            lastFile._frecv = (lastFile._frecv || 0) + 1;
            lastFile.progress = Math.round((lastFile._frecv / lastFile._fchunks) * 100);
          }
          return;
        }
        const msg = JSON.parse(e.data);
        if (msg.type === 'peer_status') {
          peerOnline.value = msg.online;
          return;
        }
        if (msg.type === 'identity_created') {
          myPubkey.value = msg.pubkey;
          localStorage.setItem('cp_my_pubkey', msg.pubkey);
          ws.value.send(JSON.stringify({type:'lan_hello', pubkey: msg.pubkey}));
          return;
        }
        if (msg.type === 'identity') {
          if (myPubkey.value) {
            ws.value.send(JSON.stringify({type:'lan_hello', pubkey: myPubkey.value}));
          } else {
            ws.value.send(JSON.stringify({type:'create_identity'}));
          }
          return;
        }
        if (msg.type === 'typing') {
          typingText.value = msg.from + ' 正在输入...';
          clearTimeout(typingTimeout);
          typingTimeout = setTimeout(() => { typingText.value = ''; }, 3000);
          return;
        }
        if (msg.type === 'file_start') {
          const fid = 'recv_' + Date.now();
          addMsg((msg.from||'').slice(0,12), `[接收中: ${msg.name}]`, 'in', fid);
          const rm = messages.value.find(x => x.id === fid);
          if (rm) { rm.progress = 0; rm._fchunks = msg.chunks || 0; rm._fname = msg.name; }
          return;
        }
        if (msg.type === 'file_end') {
          const lastFile = [...messages.value].reverse().find(x => x.dir === 'in' && x.progress != null && x._fname === msg.name);
          if (lastFile) { lastFile.progress = 100; lastFile.text = `[file: ${msg.name}]`; }
          return;
        }
        if (msg.type === 'file') {
          addMsg(msg.from, `[file: ${msg.name} (${(msg.size/1024).toFixed(1)}KB)]`, 'in', msg.id);
          return;
        }
        if (msg.type === 'file_ok') {
          const lastOut = [...messages.value].reverse().find(x => x.dir === 'out' && !x.delivered);
          if (lastOut) { lastOut.id = msg.name; lastOut.delivered = true; }
          return;
        }
        if (msg.type === 'error') {
          addMsg('system', msg.msg, 'in');
          return;
        }
        if (msg.type === 'read_receipt') {
          const m = messages.value.find(x => x.id === msg.event_id);
          if (m) m.read = true;
          return;
        }
        if (msg.type === 'reaction') {
          const m = messages.value.find(x => x.id === msg.event_id);
          if (m) m.reactions = (m.reactions || '') + msg.emoji;
          return;
        }
        if (msg.type === 'msg' || msg.from) {
          if (msg.from === 'me') {
            // Echo from proxy — update last outgoing with real id and delivered status
            const lastOut = [...messages.value].reverse().find(x => x.dir === 'out' && !x.id);
            if (lastOut) {
              lastOut.id = msg.id || lastOut.id;
              lastOut.delivered = msg.delivered;
            }
            return;
          }
          // Resolve sender to a full pubkey (msg.from may be full pk or 12-char prefix)
          const fromRaw = msg.from || '';
          const senderFull = resolvePeer(fromRaw);
          const sender = (senderFull || fromRaw).slice(0, 12);
          if (senderFull && senderFull === currentPeer.value) {
            // Message belongs to the open chat — render it
            addMsg(sender, msg.text, 'in', msg.id);
            if (msg.id && document.visibilityState === 'visible') {
              ws.value.send(JSON.stringify({type:'read_receipt', event_id: msg.id, peer: msg.from}));
            }
          } else {
            // Message for another chat — bump unread badge, don't render
            bumpUnread(senderFull || fromRaw, sender, msg.text);
          }
          if (document.hidden && Notification.permission === 'granted') {
            new Notification('CipherPipe: ' + sender, {body: (msg.text || '').slice(0, 100)});
          }
        }
        if (msg.type === 'search_results') {
          messages.value = [];
          if (msg.data && msg.data.length > 0) {
            for (const m of msg.data) {
              addMsg(m.pubkey.slice(0,12), m.content, m.direction, m.event_id);
            }
          }
        }
        if (msg.type === 'history') {
          if (msg.data) {
            for (const m of msg.data) {
              addMsg(m.pubkey.slice(0,12), m.content, m.direction, m.event_id, true, m.delivered);
            }
          }
        }
      };
    }

    function createIdentity() {
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN) return;
      copied.value = false;
      ws.value.send(JSON.stringify({type:'create_identity'}));
    }

    function copyPubkey() {
      navigator.clipboard.writeText(myPubkey.value);
      copied.value = true;
    }

    // Resolve a sender (full pk or 12-char prefix) to a known peer's full pubkey
    function resolvePeer(fromRaw) {
      if (!fromRaw) return null;
      if (currentPeer.value && (currentPeer.value === fromRaw || currentPeer.value.startsWith(fromRaw) || fromRaw.startsWith(currentPeer.value.slice(0,12)))) {
        return currentPeer.value;
      }
      const p = peers.value.find(x => x.pubkey === fromRaw || x.pubkey.startsWith(fromRaw) || fromRaw.startsWith(x.pubkey.slice(0,12)));
      return p ? p.pubkey : null;
    }

    // Message arrived for a chat that isn't open — track unread
    function bumpUnread(fullPk, shortPk, text) {
      let p = peers.value.find(x => x.pubkey === fullPk);
      if (!p && fullPk && fullPk.length >= 60) {
        // Unknown sender — auto-add to contact list
        p = { pubkey: fullPk, petname: '', unread: 0 };
        peers.value.push(p);
        savePeers();
      }
      if (p) {
        p.unread = (p.unread || 0) + 1;
        p.lastMsg = (text || '').slice(0, 40);
      }
    }

    function addMsg(from, text, dir, eventId, prepend = false, delivered = false) {
      const m = { id: eventId || 'm' + (++msgId), from, text, dir, delivered, read: false, progress: null, reactions: '', hover: false };
      if (prepend) messages.value.unshift(m);
      else messages.value.push(m);
      nextTick(() => {
        if (msgContainer.value) msgContainer.value.scrollTop = msgContainer.value.scrollHeight;
      });
    }

    function send() {
      const text = inputText.value.trim();
      if (!text || !ws.value || ws.value.readyState !== WebSocket.OPEN || !currentPeer.value) return;
      addMsg('me', text, 'out');
      ws.value.send(JSON.stringify({type:'msg', text, to: currentPeer.value}));
      inputText.value = '';
    }

    function sendFile() {
      const inp = document.createElement('input');
      inp.type = 'file';
      inp.onchange = async () => {
        const file = inp.files[0];
        if (!file || !currentPeer.value) return;
        const CHUNK = 256 * 1024, chunks = Math.ceil(file.size / CHUNK);
        const msgId = 'prog_' + Date.now();
        addMsg('me', `[文件: ${file.name} (${(file.size/1024).toFixed(1)}KB)]`, 'out', msgId);
        // Progress bar placeholder
        const m = messages.value.find(x => x.id === msgId);
        if (m) m.progress = 0;
        ws.value.send(JSON.stringify({type:'file', name:file.name, size:file.size, chunks, to: currentPeer.value}));
        for (let i = 0; i < chunks; i++) {
          ws.value.send(file.slice(i * CHUNK, (i + 1) * CHUNK));
          if (m) m.progress = Math.round(((i + 1) / chunks) * 100);
        }
        ws.value.send(JSON.stringify({type:'file_end', name:file.name}));
      };
      inp.click();
    }

    function onTyping() {
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN || !currentPeer.value) return;
      ws.value.send(JSON.stringify({type:'typing', to: currentPeer.value}));
    }

    function react(m, emoji) {
      if (!ws.value || !currentPeer.value) return;
      m.reactions = (m.reactions || '') + emoji;
      ws.value.send(JSON.stringify({type:'reaction', peer: currentPeer.value, event_id: m.id, emoji}));
    }

    function delMsg(m) {
      messages.value = messages.value.filter(x => x.id !== m.id);
      if (ws.value && currentPeer.value) {
        ws.value.send(JSON.stringify({type:'delete_msg', event_id: m.id, peer: currentPeer.value}));
      }
    }

    function addPeer() {
      const pubkey = prompt('对方公钥 (hex):');
      if (!pubkey) return;
      const petname = prompt('别名 (可选):') || '';
      const existing = peers.value.find(p => p.pubkey === pubkey);
      if (existing) { existing.petname = petname; }
      else { peers.value.push({pubkey, petname}); }
      savePeers();
      switchPeer(pubkey);
    }

    function delPeer(pubkey) {
      peers.value = peers.value.filter(p => p.pubkey !== pubkey);
      if (currentPeer.value === pubkey) currentPeer.value = null;
      savePeers();
      if (ws.value && ws.value.readyState === WebSocket.OPEN) {
        ws.value.send(JSON.stringify({type:'delete_contact', pubkey}));
      }
    }

    function switchPeer(pubkey) {
      currentPeer.value = pubkey;
      messages.value = [];
      typingText.value = '';
      isSearching = false;
      searchQuery.value = '';
      peerOnline.value = false;
      const p = peers.value.find(x => x.pubkey === pubkey);
      if (p) p.unread = 0;
      if (ws.value && ws.value.readyState === WebSocket.OPEN) {
        ws.value.send(JSON.stringify({type:'history', peer: pubkey, limit: 50}));
        ws.value.send(JSON.stringify({type:'peer_status', pubkey}));
      }
    }

    function savePeers() {
      localStorage.setItem('cp_peers', JSON.stringify(peers.value));
    }

    function search() {
      if (!searchQuery.value) {
        if (isSearching) { messages.value = [...savedMessages]; isSearching = false; }
        return;
      }
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN) return;
      if (!isSearching) { savedMessages = [...messages.value]; isSearching = true; }
      ws.value.send(JSON.stringify({type:'search', query: searchQuery.value}));
    }

    onMounted(() => {
      connect();
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          // Send read receipts for all un-read incoming messages
          for (const m of messages.value) {
            if (m.dir === 'in' && m.id && !m.read) {
              m.read = true;
              if (ws.value && ws.value.readyState === WebSocket.OPEN) {
                ws.value.send(JSON.stringify({type:'read_receipt', event_id: m.id, peer: m.from}));
              }
            }
          }
        }
      });
    });

    return {
      currentPeer, myPubkey, copied, dark, peers, messages, inputText, searchQuery, statusText, statusClass,
      typingText, chatTitle, isChatOpen, msgContainer, themeLabel, toggleTheme, avatarColor,
      send, sendFile, onTyping, react, delMsg, addPeer, delPeer, switchPeer, search, createIdentity, copyPubkey
    };
  }
}).mount('#app');
</script>
</body>
</html>
