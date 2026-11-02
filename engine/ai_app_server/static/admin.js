/* AI App Server: self-contained admin interface, no external frontend runtime. */
'use strict';
const root=document.getElementById('shell');
const state={user:null,csrf:'',permissions:[],page:'dashboard',roles:[],selectedRole:null,settings:{},busy:false,version:''};
const icons={
 server:'<rect x="4" y="3" width="16" height="7" rx="2"/><rect x="4" y="14" width="16" height="7" rx="2"/><path d="M8 6.5h.01M8 17.5h.01M12 6.5h5M12 17.5h5"/>',
 dashboard:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 shield:'<path d="m12 22 0 0c-6-3-9-7-9-13V5l9-3 9 3v4c0 6-3 10-9 13Z"/><path d="m9 12 2 2 4-4"/>',
 users:'<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M8.5 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
 roles:'<rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="9" r="2"/><path d="M8 16c.7-3 7.3-3 8 0"/>',
 permissions:'<circle cx="8" cy="15" r="4"/><path d="M11 12 20 3l2 2-3 3 1 2-3 3-2-1"/>',
 database:'<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 4 18 4 18 0V5M3 12c0 4 18 4 18 0"/>',
 maintenance:'<path d="M14.7 6.3a5 5 0 0 0-6.4 6.4L2 19l3 3 6.3-6.3a5 5 0 0 0 6.4-6.4L14 13l-3-3 3.7-3.7Z"/>',
 settings:'<circle cx="12" cy="12" r="3"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M4.93 4.93l2.12 2.12m9.9 9.9 2.12 2.12m0-14.14-2.12 2.12m-9.9 9.9-2.12 2.12"/>',
 audit:'<path d="M8 3h13M8 8h13M8 13h13M8 18h13M3 3h.01M3 8h.01M3 13h.01M3 18h.01"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
 refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 8a7 7 0 0 1 12-2l2 6M4 12l2 6a7 7 0 0 0 12-2"/>',
 lock:'<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
 logout:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 eye:'<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z"/><circle cx="12" cy="12" r="3"/>',
 warning:'<path d="M12 3 2 21h20L12 3ZM12 9v5M12 18h.01"/>',
 external:'<path d="M13 5h6v6M19 5l-9 9M19 13v6H5V5h6"/>',
 activity:'<path d="M2 12h5l3-8 4 16 3-8h5"/>',
 spark:'<path d="m3 17 6-6 4 4 8-9M17 6h4v4"/>',
 list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
 userplus:'<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M8.5 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM19 8v8m-4-4h8"/>',
 power:'<path d="M12 2v10M18.4 6a9 9 0 1 1-12.8 0"/>',
 save:'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2ZM7 3v6h10V3M7 21v-8h10v8"/>',
 more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
};
const ic=(name,cls='icon')=>`<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.server}</svg>`;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty=s=>String(s||'').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
const date=s=>s?new Date(s).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'Never';
const can=p=>state.permissions.includes(p);
const roleTone=r=>r==='Super Admin'?'purple':r==='Administrator'?'blue':r==='Operator'?'gold':'gray';
const badge=(label,tone='blue')=>`<span class="badge ${tone}">${esc(label)}</span>`;
const panelHead=(title,subtitle='',icon='shield',other='')=>`<div class="panel-head"><div class="panel-title-wrap"><span class="panel-icon">${ic(icon)}</span><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div></div>${other}</div>`;
const empty=(title,description)=>`<div class="empty">${ic('list')}<strong>${esc(title)}</strong><p>${esc(description)}</p></div>`;
const eventItem=e=>`<div class="event"><span class="event-mark">${ic(e.action.includes('login')?'lock':e.action.includes('database')?'database':e.action.includes('user')?'users':'activity')}</span><div><div class="event-title">${esc(pretty(e.action))}</div><div class="event-meta">${esc(e.actor)} ${e.target?'• '+esc(e.target):''}</div></div><span class="event-time">${date(e.created_at)}</span></div>`;
function toast(msg,failed=false){const box=document.createElement('div');box.className='toast'+(failed?' error':'');box.textContent=msg;document.getElementById('toast-region').append(box);setTimeout(()=>box.remove(),3600)}
async function api(path, options={}){
 const headers={'Accept':'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...(options.method&&options.method!=='GET'?{'X-CSRF-Token':state.csrf}:{})};
 let resp;
 try{resp=await fetch('/api/admin'+path,{credentials:'same-origin',...options,headers:{...headers,...(options.headers||{})}})}catch(e){throw new Error('Server unavailable — check the Python terminal.')}
 const data=await resp.json().catch(()=>({}));
 if(!resp.ok){if(resp.status===401&&state.user){state.user=null;renderLogin()}throw new Error(data.detail||'Request failed')}
 return data;
}
function renderLogin(error=''){
 root.innerHTML=`<div class="login-scene"><div class="login-feature"><span class="login-logo">✦</span><h1>Powerful applications.<br>Your own infrastructure.</h1><p>Manage your AI App Server securely, entirely on your own machine or server.</p><div class="login-details"><span>◉ Self-hosted</span><span>✧ Encrypted sessions</span><span>▣ SQLite by default</span></div></div><div class="login-box"><div class="login-card"><div class="logo-icon">${ic('server')}</div><div class="eyebrow">SECURE SERVER ACCESS</div><h2>Welcome back.</h2><p>Sign in to your server administration panel.</p>${error?`<div class="notice red">${ic('warning')}${esc(error)}</div>`:''}<form id="loginForm"><div class="form-field"><label for="username">Username</label><input class="input" id="username" name="username" autocomplete="username" required autofocus placeholder="Administrator username"></div><div class="form-field"><label for="password">Password</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required placeholder="Enter your password"></div><button class="btn btn-primary" type="submit">Sign in ${ic('arrow')}</button></form><button class="forgot-link" type="button" data-action="forgot">Forgot your password?</button><div class="login-foot">The admin area controls only this server, not your application's users.</div></div></div></div>`;
}
function renderForgot(){
 root.innerHTML=`<div class="login-scene"><div class="login-feature"><span class="login-logo">✦</span><h1>Secure account recovery.</h1><p>Receive a private, one-time password reset link at your verified administrator email address.</p></div><div class="login-box"><div class="login-card"><div class="logo-icon">${ic('lock')}</div><div class="eyebrow">ACCOUNT RECOVERY</div><h2>Forgot password?</h2><p>Enter your verified administrator email address. If an account exists and email delivery is configured, we'll send a link.</p><form id="forgotForm"><div class="form-field"><label>Email address</label><input class="input" type="email" name="email" maxlength="254" autocomplete="email" required placeholder="name@example.com"></div><button class="btn btn-primary" type="submit">Send reset link ${ic('arrow')}</button></form><button class="forgot-link" data-action="back-login">Back to sign in</button></div></div></div>`;
}
function renderTokenForm(type,token){
 const verifying=type==='verify';
 root.innerHTML=`<div class="login-scene"><div class="login-feature"><span class="login-logo">✦</span><h1>${verifying?'Verify your email.':'Reset your password.'}</h1><p>Secure, single-use links that expire in 30 minutes.</p></div><div class="login-box"><div class="login-card"><div class="logo-icon">${ic('shield')}</div><div class="eyebrow">SECURE ADMIN ACCESS</div><h2>${verifying?'Confirm email address':'Choose a new password'}</h2><p>${verifying?'Confirm this address belongs to your administrator account.':'Your new password must have at least 12 characters.'}</p><form id="${verifying?'verifyForm':'resetLinkForm'}"><input type="hidden" name="token" value="${esc(token)}">${verifying?'':`<div class="form-field"><label>New password</label><input class="input" name="new_password" type="password" required minlength="12" autocomplete="new-password"></div><div class="form-field"><label>Confirm password</label><input class="input" name="confirm_password" type="password" required minlength="12" autocomplete="new-password"></div>`}<button class="btn btn-primary" type="submit">${verifying?'Verify my email':'Reset password'} ${ic('arrow')}</button></form><button class="forgot-link" data-action="back-login">Back to sign in</button></div></div></div>`;
}
function showRecoveryRoute(){
 const params=new URLSearchParams(location.search);
 if(params.has('reset-password')){renderTokenForm('reset',params.get('reset-password'));return true}
 if(params.has('verify-email')){renderTokenForm('verify',params.get('verify-email'));return true}
 return false;
}
const navigation=[['dashboard','Dashboard','dashboard'],['security','Security','shield'],['users','Users','users'],['app-users','App Users','users'],['roles','Roles','roles'],['permissions','Permissions','permissions'],['databases','Databases','database'],['maintenance','Maintenance','maintenance'],['service','Service','server'],['mcp','MCP','settings'],['settings','Settings','settings'],['audit','Audit Log','audit']];
function renderShell(){
 root.innerHTML=`<div class="shell"><aside class="sidebar"><div class="logo"><span class="logo-icon">${ic('server')}</span><div><strong>AI App Server</strong><small>Control Center</small></div></div><div class="nav-label">WORKSPACE</div><nav>${navigation.map(([p,label,icon])=>`<button class="nav-item ${state.page===p?'active':''}" data-nav="${p}" title="${label}">${ic(icon)}<span>${label}</span></button>`).join('')}</nav><div class="sidebar-bottom"><div class="sidebar-health"><span class="online-dot"></span> Server online</div><small>${esc(state.version?'v'+state.version:'Version unknown')} • Independently hosted</small></div></aside><div class="workspace"><header class="topbar"><div class="bread"><span>Server Administration</span><span class="slash">/</span><strong id="breadcrumb">${navigation.find(n=>n[0]===state.page)?.[1]}</strong></div><div class="top-actions"><span class="environment"><span class="online-dot"></span> Self-hosted</span><span class="divider-v"></span><button class="user-chip" data-action="account" title="Change password"><span class="avatar">${esc(state.user.username.slice(0,2).toUpperCase())}</span><span>${esc(state.user.username)}</span></button><button class="btn btn-outline btn-small" data-action="logout" title="Sign out">${ic('logout')}</button></div></header><main class="main" id="main"><div class="loading"><div class="spinner"></div></div></main></div></div>`;
}
function header(eyebrow,title,sub,buttons=''){return `<div class="page-head"><div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1><p class="sub">${esc(sub)}</p></div><div class="page-tools">${buttons}</div></div>`}
async function loadPage(page=state.page){
 if(!state.user)return;
 state.page=page;
 document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.nav===page));
 const crumb=document.getElementById('breadcrumb');if(crumb)crumb.textContent=navigation.find(n=>n[0]===page)?.[1]||page;
 const main=document.getElementById('main');if(!main)return;
 main.innerHTML='<div class="loading"><div class="spinner"></div></div>';
 if(state.user.must_change_password){main.innerHTML=header('FIRST-RUN SETUP','Secure your administrator account','Change the temporary password to continue.');passwordModal(true);return}
 try{
  const map={dashboard:renderDashboard,security:renderSecurity,users:renderUsers,'app-users':renderApplicationUsers,roles:renderRoles,permissions:renderPermissions,databases:renderDatabases,maintenance:renderMaintenance,service:renderService,mcp:renderMcp,settings:renderSettings,audit:renderAudit};
  main.innerHTML=await map[page]();
 }catch(e){main.innerHTML=`${header('SERVER ADMINISTRATION','Unable to load this page',e.message)}<div class="notice red">${ic('warning')}${esc(e.message)}</div>`}
}
async function renderDashboard(){
 const d=await api('/dashboard');
 return header('OVERVIEW','Server Dashboard','This application, its configuration, security and activity.',`<button class="btn btn-outline" data-action="reload">${ic('refresh')} Refresh</button>`)+
 `<div class="hero"><div class="hero-content"><div class="eyebrow" style="color:#a4c2ff">THE FRAMEWORK IS RUNNING</div><h2>One application.<br>Its own secure server.</h2><p>A private admin area for this Python application. No central registry, no other systems, and no cloud account.</p><button class="btn" data-action="open-app">${ic('external')} Open application</button></div><div class="hero-art"><div class="hero-orb"></div><div class="hero-line"></div><div class="hero-terminal"><span></span><span></span><span></span><span></span></div></div></div>
 <div class="grid cols-4"><div class="panel kpi"><span class="kpi-symbol">${ic('users')}</span><div><strong>${d.users}</strong><label>Active administrators</label></div></div><div class="panel kpi"><span class="kpi-symbol purple">${ic('roles')}</span><div><strong>${d.roles}</strong><label>Server roles</label></div></div><div class="panel kpi"><span class="kpi-symbol green">${ic('database')}</span><div><strong>${d.databases}</strong><label>Database connections</label></div></div><div class="panel kpi"><span class="kpi-symbol ${d.maintenance?'gold':'green'}">${ic('power')}</span><div><strong>${d.maintenance?'Offline':'Online'}</strong><label>Application status</label></div></div></div>
 <div class="two-panel section-space"><section class="panel">${panelHead('Recent activity','Latest server administration events','activity',`<button class="btn btn-outline btn-small" data-nav="audit">View audit log</button>`)}<div class="event-list">${d.recent.length?d.recent.map(eventItem).join(''):empty('No activity yet','Administrator changes will appear here.')}</div></section><section class="panel">${panelHead('Server information','Current running environment','server')}<div class="server-row"><span>Framework version</span><strong>${esc(d.server.version)}</strong></div><div class="server-row"><span>Application</span><strong>${esc(d.server.script)}</strong></div><div class="server-row"><span>Environment</span><strong>${esc(pretty(d.server.mode))}</strong></div><div class="server-row"><span>Python version</span><strong>${esc(d.server.python)}</strong></div><div class="server-row"><span>Host operating system</span><strong>${esc(d.server.os)}</strong></div><div class="server-row"><span>System database</span><strong>SQLite ${badge('Active','green')}</strong></div></section></div>`;
}
async function renderService(){
 if(!can('view_service'))throw new Error('You do not have permission to view this application.');
 const d=await api('/service');const p=d.hosting.port;
 return header('THIS APPLICATION ONLY','Background Hosting & Port','Your current Python application only. Other projects remain separate.',`<button class="btn btn-outline" data-action="reload">${ic('refresh')} Refresh</button>`)+
 `<div class="hero"><div class="hero-content"><div class="eyebrow" style="color:#b0c8ff">LOCAL BACKGROUND MODE</div><h2>Your app. Simple to run.</h2><p>One click installs, starts and opens your own application. No extra service software, account setup or terminal window.</p></div><div class="hero-art"><div class="hero-orb"></div><div class="hero-line"></div><div class="hero-terminal"><span></span><span></span><span></span><span></span></div></div></div>`+
 `<div class="two-panel section-space"><section class="panel">${panelHead('Windows startup','Your application runs after you sign in to Windows.','server',badge(d.status,d.running?'green':'gold'))}
 <div class="server-row"><span>Application</span><strong>${esc(d.application)}</strong></div>
 <div class="server-row"><span>Running status</span><strong>${esc(d.status)}</strong></div>
 <div class="server-row"><span>Startup type</span><strong>Background at Windows sign-in</strong></div>
 <div class="notice section-space">${ic('check')} <div><strong>Easy setup:</strong> Double-click <strong>START HERE.bat</strong> in the project folder. It installs, starts and opens the web application automatically.</div></div>
 <div class="notice amber section-space">${ic('warning')} This is user-level background startup, not a machine-wide Windows Service. The app starts after you sign in, and stops when Windows signs you out or shuts down.</div>
 </section><section class="panel">${panelHead('Application address','Choose this application\'s local port.','settings')}
 <form id="hostingForm"><div class="form-field"><label for="hostingPort">Port number</label><input class="input" id="hostingPort" type="number" name="port" min="1024" max="65535" value="${p}" required ${can('manage_settings')?'':'disabled'}><span class="form-help">Default 8501. Each Python project can have its own port.</span></div>
 <div class="form-field"><label for="hostingMode">Deployment environment</label><select class="input" name="mode" id="hostingMode" ${can('manage_settings')?'':'disabled'}><option value="development" ${d.hosting.mode==='development'?'selected':''}>Development — local HTTP, no SSL required</option><option value="production" ${d.hosting.mode==='production'?'selected':''}>Production — HTTPS proxy and private app login required</option></select><span class="form-help">Production cannot be activated until the security checks pass. Settings take effect after restart.</span></div>
 <div class="server-row"><span>Binding</span><strong>127.0.0.1 (this computer only)</strong></div>
 <div class="server-row"><span>Saved port</span><strong>http://127.0.0.1:${p}</strong></div>
 <button class="btn btn-primary" type="submit" ${can('manage_settings')?'':'disabled'}>${ic('save')} Save port</button></form>
 <div class="notice amber section-space">${ic('warning')} After changing the port, double-click <strong>Stop AI App Server.bat</strong>, then <strong>Open AI App Server.bat</strong> to restart. The SQLite database is never replaced.</div></section></div>`;
}

async function renderMcp(){
 if(!can('view_service'))throw new Error('Server view permission required.');
 const d=await api('/mcp');
 return header('OPTIONAL MCP MODULE','MCP Tools & Connections','Connect this application to compatible MCP clients. Disabled by default.')+
 `<div class="grid cols-2"><section class="panel">${panelHead('MCP endpoint','Available only to clients with your private token','shield')}
 <div class="server-row"><span>Status</span>${badge(d.enabled?'Enabled':'Disabled',d.enabled?'green':'gray')}</div>
 <div class="server-row"><span>Endpoint</span><code>/mcp</code></div>
 <div class="server-row"><span>Protocol</span><strong>${esc(d.protocol)}</strong></div>
 <p class="sub">Your tools belong only to this application. Other AI App Server installations remain separate.</p>
 <div class="row-actions section-space">${can('manage_settings')?`<button class="btn btn-primary" data-action="mcp-enable">${ic('lock')} ${d.enabled?'Rotate access token':'Enable MCP and create token'}</button> ${d.enabled?`<button class="btn btn-outline" data-action="mcp-disable">Disable MCP</button>`:''}`:'Contact an administrator to change settings.'}</div>
 <div id="mcp-token-panel" class="section-space"></div>
 </section><section class="panel">${panelHead('Registered tools','Added explicitly in your project: app/mcp_tools.py','list')}
 ${d.tool_load_error?`<div class="notice amber">Tool file could not load. Check app/mcp_tools.py, then restart this application.</div>`:""}${d.tools.length?d.tools.map(t=>`<div class="server-row"><span><strong>${esc(t.name)}</strong><br><small>${esc(t.description)}</small></span>${badge('Read-only','green')}</div>`).join(''):empty('No tools registered','Add app/mcp_tools.py to expose tools written by your developer.')}
 <div class="notice amber section-space">${ic('warning')} Do not expose secrets, shell commands or unrestricted database access. Only trusted, read-only tools are available in this release.</div></section></div>`;
}

async function renderSecurity(){
 const d=await api('/security');
 const pre=await api('/production-check');
 return header('ACCESS CONTROL','Security & Server Admin','Safeguards and controls for this AI App Server.',`<button class="btn btn-primary" data-action="account">${ic('lock')} Change my password</button>`)+
 `<section class="panel section-space">${panelHead('Production readiness checks','These checks must pass before production mode can be enabled. They do not replace a security audit.','shield')}${pre.checks.map(c=>`<div class="server-row"><span>${esc(c.message)}</span>${badge(c.ok?'Passed':'Action required',c.ok?'green':'gold')}</div>`).join('')}</section>`+
 `<div class="notice ${d.localhost_only?'green':'amber'}">${ic('shield')}<div><strong>${d.localhost_only?'Local development access':'Network-accessible server'}</strong><br>${d.localhost_only?'The app server listens on localhost. You can access your applications locally while developing.':'Network deployment requires HTTPS, authentication and a securely configured reverse proxy.'}</div></div>
 <div class="grid cols-3 section-space"><div class="panel">${panelHead('Admin authentication','Protected management area','lock')}<h2>${badge('Enabled','green')}</h2><p class="sub">Session cookies, protected endpoints and role checks are active.</p></div><div class="panel">${panelHead('Request protection','Cross-site request forgery','shield')}<h2>${badge('Enabled','green')}</h2><p class="sub">Origin checks, CSRF token and restrictive cookie policies.</p></div><div class="panel">${panelHead('Login protection','Attempt limits and auditing','activity')}<h2>${badge('5 attempts / 15 mins','blue')}</h2><p class="sub">Failed logins are tracked and repeated attempts are blocked.</p></div></div>
 <div class="two-panel section-space"><section class="panel">${panelHead('My administrator account','Security settings for the signed-in account','users')}<div class="server-row"><span>Username</span><strong>${esc(state.user.username)}</strong></div><div class="server-row"><span>Role</span>${badge(state.user.role,roleTone(state.user.role))}</div><div class="server-row"><span>Recovery email</span><strong>${esc(state.user.email||'Not set')}</strong></div><div class="server-row"><span>Email verification</span>${badge(state.user.email_verified?'Verified':'Not verified',state.user.email_verified?'green':'gold')}</div>${!state.user.email_verified?`<div class="notice amber section-space">${ic('warning')} Verify your email to enable password recovery. Email delivery requires SMTP configuration.</div><button class="btn btn-outline btn-small section-space" data-action="resend-verification">Send verification email</button>`:''}<div class="server-row"><span>Last login</span><strong>${date(state.user.last_login)}</strong></div><div class="server-row"><span>Password policy</span><strong>Minimum 12 characters</strong></div><div class="section-space"><button class="btn btn-primary" data-action="account">${ic('lock')} Update password</button></div></section><section class="panel">${panelHead('Deployment safeguards','Recommended checks before public access','shield')}<div class="server-row"><span>Origin checks</span>${badge('Enabled','green')}</div><div class="server-row"><span>Secure cookies</span>${badge(d.secure_cookies?'Enabled':'Local HTTP',d.secure_cookies?'green':'gold')}</div><div class="server-row"><span>HTTP security headers</span>${badge('Enabled','green')}</div><div class="server-row"><span>Admin user database</span>${badge('SQLite','blue')}</div><div class="notice amber section-space">${ic('warning')} This is an early release. A security review is still required before internet-facing or untrusted multi-tenant deployment.</div></section></div>`;
}
async function renderUsers(){
 if(!can('manage_users'))throw new Error('You do not have permission to manage users.');
 const [data,roleData]=await Promise.all([api('/users'),api('/roles')]);state.roles=roleData.roles;
 return header('IDENTITY MANAGEMENT','Users & Administrators','Create, manage, disable and reset server administration accounts.',`<button class="btn btn-primary" data-action="new-user">${ic('userplus')} Create Administrator</button>`)+
 `<section class="panel">${panelHead('Administrator accounts',`${data.users.length} accounts configured`,'users')}
 <div class="table-wrap"><table><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th><th>Last login</th><th>Actions</th></tr></thead><tbody>${data.users.map(u=>`<tr><td><div class="cell-person"><span class="person-dot ${u.role==='Super Admin'?'violet':''}">${esc(u.username.slice(0,2).toUpperCase())}</span><strong>${esc(u.display_name)}</strong></div></td><td>${esc(u.username)}</td><td>${badge(u.role,roleTone(u.role))}</td><td>${badge(u.is_active?'Active':'Disabled',u.is_active?'green':'gray')}</td><td>${date(u.last_login)}</td><td><div class="row-actions"><button class="btn btn-outline btn-small" data-action="edit-user" data-id="${u.id}">Edit</button><button class="btn btn-outline btn-small" data-action="reset-user" data-id="${u.id}">Reset password</button>${u.id!==state.user.id?`<button class="btn btn-small ${u.is_active?'btn-danger':'btn-quiet'}" data-action="toggle-user" data-id="${u.id}" data-active="${u.is_active?'1':'0'}">${u.is_active?'Disable':'Enable'}</button>`:''}</div></td></tr>`).join('')}</tbody></table></div></section><div class="notice section-space">${ic('lock')} These users can access the server admin area only. Your Python application's end-user accounts are separate.</div>`;
}
async function renderApplicationUsers(){
 if(!can('manage_users'))throw new Error('Manage users permission required.');
 const d=await api('/app-users');
 return header('APPLICATION ACCESS','Application Users','Each person has their own login, separate from server administrators.',`<button class="btn btn-primary" data-action="new-app-user">${ic('plus')} Add App User</button>`)+
 `<section class="panel section-space">${panelHead('Application accounts','Disabling a user immediately revokes all their sessions','users')}
 <div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Email</th><th>Status</th><th>Actions</th></tr></thead><tbody>${d.users.length?d.users.map(u=>`<tr><td><strong>${esc(u.username)}</strong></td><td>${esc(u.display_name)}</td><td>${esc(u.email||'Not set')}</td><td>${badge(u.is_active?'Active':'Disabled',u.is_active?'green':'gray')}</td><td class="row-actions"><button class="btn btn-outline btn-small" data-action="app-user-reset" data-id="${u.id}">Reset password</button> <button class="btn btn-outline btn-small" data-action="app-user-toggle" data-id="${u.id}" data-active="${u.is_active?'1':'0'}">${u.is_active?'Disable':'Enable'}</button></td></tr>`).join(''):'<tr><td colspan="5">No application users. Create one before switching to Production.</td></tr>'}</tbody></table></div>
 <div class="notice amber section-space">${ic('shield')} These accounts can access the hosted application only. They are not server administrators. Development mode does not require application login.</div></section>`;
}
function newApplicationUserModal(){
 modal(`<form id="newAppUserForm"><div class="form-field"><label>Username</label><input class="input" name="username" required minlength="3" maxlength="60" pattern="[A-Za-z0-9_.-]+" autocomplete="off"></div><div class="form-field"><label>Full name</label><input class="input" name="display_name" required maxlength="100"></div><div class="form-field"><label>Email (optional)</label><input class="input" name="email" type="email" maxlength="254"></div><div class="form-field"><label>Individual password (minimum 12 characters)</label><input class="input" name="password" type="password" minlength="12" autocomplete="new-password" required></div><footer><button class="btn btn-outline" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">Create app user</button></footer></form>`,'Create Application User');
}
async function renderRoles(){
 const d=await api('/roles');state.roles=d.roles;
 return header('ACCESS CONTROL','Server Roles','Each administrator is assigned a role with permissions restricted to server administration.',can('manage_roles')?`<button class="btn btn-primary" data-action="new-role">${ic('plus')} Create role</button>`:'')+
 `<div class="grid cols-2">${d.roles.map(role=>`<section class="panel"><div class="flex-between"><div class="panel-title-wrap"><span class="panel-icon">${ic(role.name==='Super Admin'?'shield':'roles')}</span><div><h2>${esc(role.name)}</h2><p class="sub">${esc(role.description||'Custom server role')}</p></div></div>${badge(role.is_system?'Built-in':'Custom',role.is_system?'blue':'purple')}</div><hr class="hr"><div class="flex-between"><span class="muted small">${role.permissions.length} permissions enabled</span><button class="btn btn-outline btn-small" data-nav="permissions" data-role="${role.id}">View permissions ${ic('arrow')}</button></div></section>`).join('')}</div>`;
}
async function renderPermissions(){
 const d=await api('/roles');state.roles=d.roles;
 const selected=d.roles.find(r=>r.id===state.selectedRole)||d.roles.find(r=>r.name==='Administrator')||d.roles[0];state.selectedRole=selected.id;
 return header('ACCESS CONTROL','Roles & Permissions','Decide exactly which server functions each role can use.')+
 `<section class="panel">${panelHead('Role permission matrix','Changes take effect after saving. Existing sessions for that role are revoked.','permissions')}<div class="role-selector">${d.roles.map(r=>`<button class="role-choice ${r.id===selected.id?'active':''}" data-action="choose-role" data-id="${r.id}">${esc(r.name)}</button>`).join('')}</div><div class="notice section-space">${ic('shield')} Application-level users and permissions are not controlled here. This matrix applies to the AI App Server administration section only.</div><div class="table-wrap section-space"><table class="permission-table"><thead><tr><th>Server permission</th><th>Allow</th></tr></thead><tbody>${Object.entries(d.permission_catalog).map(([key,label])=>`<tr><td><strong>${esc(label)}</strong><div class="muted small">${esc(key)}</div></td><td><input class="permission-box" type="checkbox" value="${esc(key)}" ${selected.permissions.includes(key)?'checked':''} ${selected.name==='Super Admin'||!can('manage_roles')?'disabled':''} aria-label="Allow ${esc(label)}"></td></tr>`).join('')}</tbody></table></div>${selected.name==='Super Admin'?`<div class="notice amber section-space">${ic('lock')} Super Admin permissions are locked to prevent administrative lockout.</div>`:can('manage_roles')?`<div class="row-actions section-space"><button class="btn btn-primary" data-action="save-role-permissions" data-id="${selected.id}">${ic('save')} Save permissions</button></div>`:''}</section>`;
}
async function renderDatabases(){
 if(!can('manage_databases'))throw new Error('You do not have permission to manage databases.');
 const d=await api('/databases');
 return header('CONNECTION MANAGEMENT','Databases','Your server starts with SQLite. Add other database connections whenever your projects need them.',`<button class="btn btn-primary" data-action="new-db">${ic('plus')} Add database</button>`)+
 `<section class="panel">${panelHead('Database connections','Connection details are encrypted at rest.','database')}${d.connections.map(conn=>`<div class="database ${conn.default?'system':''}"><div class="db-icon">${ic('database')}</div><div><strong>${esc(conn.name)}</strong><p>${conn.default?esc(conn.path):esc(conn.engine.toUpperCase()+' connection • Credentials hidden')}</p></div><div class="db-end">${badge(conn.default?'Default':'Configured',conn.default?'green':'gray')}<button class="btn btn-outline btn-small" data-action="test-db" data-id="${conn.id}">Test</button>${conn.default?'':`<button class="btn btn-danger btn-small" data-action="delete-db" data-id="${conn.id}" data-name="${esc(conn.name)}">Remove</button>`}</div></div>`).join('')}</section><div class="notice section-space">${ic('database')} <div><strong>SQLite is the built-in system database.</strong><br>It stores administrators, permissions, server settings, connection profiles and the audit log. It cannot be removed. Other connections are optional and require their respective Python database drivers.</div></div>`;
}
async function renderMaintenance(){
 if(!can('manage_maintenance'))throw new Error('You do not have permission to manage maintenance mode.');
 const d=await api('/settings');const s=d.settings;state.settings=s;const active=s.maintenance_enabled;
 return header('SERVER OPERATIONS','Maintenance Mode','Take your application frontend offline while keeping administrator access available.',`<button class="btn btn-outline" data-action="preview-maintenance">${ic('eye')} Preview page</button>`)+
 `<div class="notice amber">${ic('warning')}<div><strong>Frontend-only maintenance.</strong><br>The public application returns HTTP 503 when maintenance is active. The protected /admin area remains available so you can switch it back on.</div></div>
 <div class="two-panel section-space"><section class="panel">${panelHead('Maintenance controls','Switch your application into a temporary maintenance state.','maintenance',badge(active?'Enabled':'Disabled',active?'gold':'green'))}<form id="maintenanceForm"><div class="flex-between"><div><h3>Enable maintenance mode</h3><p class="sub">Temporarily replace the application with the maintenance page.</p></div><button type="button" class="switch ${active?'on':''}" id="maintenanceToggle" role="switch" aria-checked="${active}"></button><input type="hidden" name="maintenance_enabled" id="maintenanceValue" value="${active}"></div><hr class="hr"><div class="form-field"><label for="maintenanceMessage">Maintenance message</label><textarea id="maintenanceMessage" name="maintenance_message" maxlength="400" required>${esc(s.maintenance_message)}</textarea><span class="form-help">Shown to visitors while the app is offline.</span></div><div class="form-field"><label for="startMaintenance">Scheduled start (optional)</label><input class="input" type="datetime-local" id="startMaintenance" name="maintenance_start" value="${localDate(s.maintenance_start)}"></div><div class="form-field"><label for="endMaintenance">Scheduled end (optional)</label><input class="input" type="datetime-local" id="endMaintenance" name="maintenance_end" value="${localDate(s.maintenance_end)}"><span class="form-help">Leave both blank for manual-only maintenance. Scheduled dates use your browser's timezone.</span></div><button class="btn btn-primary" type="submit">${ic('save')} Save maintenance settings</button></form></section>
 <section class="panel">${panelHead('Public maintenance page','This is what your application visitors will see.','eye')}<div class="maintenance-preview"><div><div class="eyebrow">SERVICE NOTICE</div><h2>Sorry, down for maintenance.</h2><p id="previewMessage">${esc(s.maintenance_message)}</p></div><img src="/static/maintenance.svg" alt="Illustrated servers under maintenance"></div><div class="row-actions section-space">${badge(active?'Frontend offline':'Frontend running',active?'gold':'green')} <button class="btn btn-outline btn-small" data-action="preview-maintenance">Open full preview ${ic('external')}</button></div><div class="notice green section-space">${ic('shield')} Administrators can still access /admin during maintenance.</div></section></div>`;
}
function localDate(s){if(!s)return '';let d=new Date(s);if(isNaN(d))return '';return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}
async function renderSettings(){
 const d=await api('/settings');const sec=await api('/security');state.settings=d.settings;
 return header('CONFIGURATION','Server Settings','Manage the server identity and your administrator password.')+
 `<div class="two-panel"><section class="panel">${panelHead('Application identity','Used in the administration and maintenance pages.','settings')}<form id="settingsForm"><div class="form-field"><label for="appTitle">Application title</label><input class="input" id="appTitle" name="app_title" maxlength="80" required value="${esc(d.settings.app_title)}"></div><button class="btn btn-primary" type="submit" ${can('manage_settings')?'':'disabled'}>${ic('save')} Save settings</button></form></section><section class="panel">${panelHead('Your password','Change your own admin credentials.','lock')}<p class="sub">For security, changing the password ends your current sessions and asks you to sign in again.</p><div class="section-space"><button class="btn btn-primary" data-action="account">${ic('lock')} Change my password</button></div><hr class="hr"><h3>Session policy</h3><p class="sub">12-hour server-side session expiry. HTTP-only, SameSite Strict cookies.</p></section></div>
 <section class="panel section-space">${panelHead('Email recovery delivery','Configure SMTP before forgotten-password emails can be sent.','lock',badge(sec.smtp_configured?'SMTP configured':'SMTP not configured',sec.smtp_configured?'green':'gold'))}<p class="sub">Email addresses are validated and verified with a single-use link. Recovery is enabled for verified addresses only. To configure an email provider, set the AI_APP_SERVER_SMTP_HOST, AI_APP_SERVER_SMTP_FROM, AI_APP_SERVER_SMTP_USER and AI_APP_SERVER_SMTP_PASSWORD environment variables, then restart the server. SMTP uses TLS. See .env.smtp.example in the project folder.</p><div class="notice ${sec.smtp_configured?'green':'amber'} section-space">${ic('shield')} ${sec.smtp_configured?'Email delivery has been configured. Verify each administrator address to enable recovery.':'Password recovery emails cannot be delivered until SMTP has been configured. Admin login still works normally.'}</div></section>`;
}
async function renderAudit(){
 if(!can('view_audit'))throw new Error('You do not have permission to view audit logs.');
 const d=await api('/audit');
 return header('OPERATIONS & COMPLIANCE','Audit Log','Review who changed server settings, accounts, roles and database connections.',`<button class="btn btn-outline" data-action="reload">${ic('refresh')} Refresh</button>`)+
 `<section class="panel">${panelHead('Security & administration activity',`Latest ${d.events.length} recorded events`,'audit')}<div class="table-wrap"><table><thead><tr><th>When</th><th>Administrator</th><th>Action</th><th>Target</th><th>Details</th></tr></thead><tbody>${d.events.map(e=>`<tr><td>${date(e.created_at)}</td><td><strong>${esc(e.actor)}</strong></td><td><span class="log-code">${esc(e.action)}</span></td><td>${esc(e.target)}</td><td>${esc(e.details)}</td></tr>`).join('')}</tbody></table></div>${d.events.length?'':empty('No audit events','Events will be recorded as server administrators make changes.')}</section>`;
}
function modal(content,title,options={}){
 document.querySelector('.modal-wrap')?.remove();
 const wrap=document.createElement('div');wrap.className='modal-wrap';wrap.innerHTML=`<section class="modal ${options.large?'large':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><h2>${esc(title)}</h2>${options.locked?'':`<button class="x" type="button" data-action="close-modal" title="Close">×</button>`}</header>${content}</section>`;document.body.append(wrap);wrap.querySelector('input,button,select')?.focus();
}
function closeModal(){document.querySelector('.modal-wrap')?.remove()}
function passwordModal(locked=false){
 modal(`${locked?`<div class="notice amber">${ic('warning')} The initial password must be changed before the admin panel can be used. Choose at least 12 characters.</div>`:''}<form id="passwordForm"><div class="form-field"><label>Recovery email address (required)</label><input class="input" name="email" type="email" maxlength="254" value="${esc(state.user.email||'')}" placeholder="name@example.com" autocomplete="email" required><span class="form-help">We use this for forgotten-password links. Verify it using the email we send (SMTP required).</span></div><div class="form-field"><label>Current password</label><input class="input" type="password" name="current_password" autocomplete="current-password" required></div><div class="form-field"><label>New password (minimum 12 characters)</label><input class="input" type="password" name="new_password" minlength="12" autocomplete="new-password" required></div><div class="form-field"><label>Confirm new password</label><input class="input" type="password" name="confirm_password" minlength="12" autocomplete="new-password" required></div><footer>${locked?'':`<button class="btn btn-outline" type="button" data-action="close-modal">Cancel</button>`}<button class="btn btn-primary" type="submit">${ic('lock')} Update password</button></footer></form>`,'Change administrator password',{locked});
}
function userModal(user=null){
 const editing=Boolean(user);
 modal(`<form id="${editing?'editUserForm':'newUserForm'}" data-id="${user?.id||''}"><div class="form-field"><label>Full name</label><input class="input" name="display_name" maxlength="100" required value="${esc(user?.display_name||'')}" placeholder="Jane Smith"></div>${editing?'':`<div class="form-field"><label>Username</label><input class="input" name="username" pattern="[A-Za-z0-9_.-]{3,60}" required placeholder="jane"></div><div class="form-field"><label>Email (optional)</label><input class="input" name="email" type="email" placeholder="jane@company.com"></div>`}<div class="form-field"><label>Role</label><select name="role_id">${state.roles.filter(r=>state.user.role==='Super Admin'||r.name!=='Super Admin').map(r=>`<option value="${r.id}" ${user?.role_id===r.id?'selected':''}>${esc(r.name)}</option>`).join('')}</select></div>${editing?'':`<div class="form-field"><label>Temporary password (minimum 12 characters)</label><input class="input" name="password" type="password" minlength="12" autocomplete="new-password" required></div><div class="notice">${ic('shield')} The new administrator must change this temporary password at first sign-in.</div>`}<footer><button class="btn btn-outline" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">${ic('save')} ${editing?'Save changes':'Create administrator'}</button></footer></form>`,editing?'Edit Administrator':'Create Administrator');
}
function newRoleModal(){modal(`<form id="newRoleForm"><div class="form-field"><label>Role name</label><input class="input" name="name" maxlength="60" required placeholder="Security Reviewer"></div><div class="form-field"><label>Description</label><input class="input" name="description" maxlength="240" placeholder="Server audit and security access"></div><div class="notice">${ic('shield')} New roles start with no permissions. Set permissions from the matrix after creating the role.</div><footer><button class="btn btn-outline" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">Create role</button></footer></form>`,'Create Server Role')}
function newDatabaseModal(){modal(`<form id="newDatabaseForm"><div class="form-field"><label>Connection name</label><input class="input" name="name" required maxlength="70" placeholder="Production reporting database"></div><div class="form-field"><label>Database engine</label><select name="engine" id="dbEngine"><option value="sqlite">SQLite</option><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL</option><option value="mssql">Microsoft SQL Server</option></select></div><div class="form-field"><label>SQLAlchemy connection URL</label><input class="input" name="url" id="dbUrl" type="password" required autocomplete="off" placeholder="sqlite:///E:/data/project.sqlite3"><span class="form-help" id="dbHelp">Use SQLAlchemy URL format. Connection details are encrypted locally and will not be displayed again.</span></div><div class="notice amber">${ic('warning')} Install the Python database driver for your chosen engine. The server does not automatically create databases.</div><footer><button class="btn btn-outline" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">${ic('plus')} Add connection</button></footer></form>`,'Add Database Connection');}
function previewMaintenance(){
 modal(`<div class="maintenance-preview"><div><div class="eyebrow">SERVICE NOTICE</div><h2>Sorry, down for maintenance.</h2><p>${esc(state.settings.maintenance_message||'We’ll be back shortly.')}</p></div><img src="/static/maintenance.svg" alt="Servers being maintained"></div><footer><button class="btn btn-primary" type="button" data-action="close-modal">Close preview</button></footer>`,'Public Maintenance Page',{large:true})
}
async function act(el){const action=el.dataset.action,id=Number(el.dataset.id);try{
 switch(action){
 case 'close-modal':closeModal();break;
 case 'logout':await api('/logout',{method:'POST'});state.user=null;state.csrf='';closeModal();renderLogin();break;
 case 'account':passwordModal();break;
 case 'forgot':renderForgot();break;
 case 'back-login':history.replaceState({},'', '/admin');renderLogin();break;
 case 'resend-verification':{const r=await api('/resend-verification',{method:'POST'});toast(r.message);break;}
 case 'reload':await loadPage();toast('Page refreshed');break;
 case 'open-app':window.open('/','_blank','noopener');break;
 case 'new-user':userModal();break;
 case 'edit-user':{const u=(await api('/users')).users.find(x=>x.id===id);userModal(u);break;}
 case 'reset-user':modal(`<p class="sub">Set a temporary password for this administrator. They will be required to change it at sign-in.</p><form id="resetUserForm" data-id="${id}"><div class="form-field"><label>New temporary password</label><input class="input" name="new_password" type="password" minlength="12" autocomplete="new-password" required></div><footer><button class="btn btn-outline" data-action="close-modal" type="button">Cancel</button><button class="btn btn-primary" type="submit">Reset password</button></footer></form>`,'Reset Administrator Password');break;
 case 'toggle-user':if(confirm(`Are you sure you want to ${el.dataset.active==='1'?'disable':'enable'} this administrator?`)){await api(`/users/${id}`,{method:'PATCH',body:JSON.stringify({is_active:el.dataset.active!=='1'})});toast('Administrator updated');await loadPage()}break;
 case 'new-app-user':newApplicationUserModal();break;
 case 'app-user-toggle':if(confirm(`Are you sure you want to ${el.dataset.active==='1'?'disable':'enable'} this application user?`)){await api(`/app-users/${id}`,{method:'PATCH',body:JSON.stringify({is_active:el.dataset.active!=='1'})});toast('App user updated');await loadPage('app-users')}break;
 case 'app-user-reset':modal(`<form id="appUserPasswordForm" data-id="${id}"><div class="form-field"><label>New password (minimum 12 characters)</label><input name="new_password" class="input" type="password" minlength="12" autocomplete="new-password" required></div><footer><button class="btn btn-outline" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">Reset and revoke sessions</button></footer></form>`,'Reset Application Password');break;
 case 'new-role':newRoleModal();break;
 case 'choose-role':state.selectedRole=id;await loadPage('permissions');break;
 case 'save-role-permissions':{const permissions=[...document.querySelectorAll('.permission-box:checked')].map(n=>n.value);await api(`/roles/${id}/permissions`,{method:'PUT',body:JSON.stringify({permissions})});toast('Role permissions saved');await loadPage();break;}
 case 'new-db':newDatabaseModal();break;
 case 'test-db':{const r=await api(`/databases/${id}/test`,{method:'POST'});toast(r.message);break;}
 case 'delete-db':if(confirm(`Remove the connection "${el.dataset.name}"? This does not delete the actual database.`)){await api(`/databases/${id}`,{method:'DELETE'});toast('Connection removed');await loadPage()}break;
 case 'mcp-enable':{
   if(!confirm('Enable MCP and generate a new access token? Any previous token will stop working.'))break;
   const r=await api('/mcp/enable',{method:'POST'});
   await loadPage();
   const panel=document.getElementById('mcp-token-panel');
   if(panel){panel.innerHTML='<div class="notice amber">Copy this token now. It will not be shown again.</div><pre id="mcp-token-value" style="overflow-wrap:anywhere;white-space:pre-wrap"></pre><button class="btn btn-outline btn-small" data-action="mcp-copy">Copy token</button>';
      document.getElementById('mcp-token-value').textContent=r.token;}
   toast('MCP enabled — save the new access token securely');break;}
 case 'mcp-disable':if(confirm('Disable MCP and revoke its access token?')){await api('/mcp/disable',{method:'POST'});await loadPage();toast('MCP disabled');}break;
 case 'mcp-copy':{
    const value=document.getElementById('mcp-token-value')?.textContent;
    if(value){await navigator.clipboard.writeText(value);toast('Token copied. Store it safely.');}break;}
 case 'preview-maintenance':previewMaintenance();break;
 default:break;
 }
 }catch(e){toast(e.message,true)}
}
document.addEventListener('click',e=>{
 const nav=e.target.closest('[data-nav]');if(nav){if(nav.dataset.role)state.selectedRole=Number(nav.dataset.role);loadPage(nav.dataset.nav);return}
 const action=e.target.closest('[data-action]');if(action){act(action);return}
 if(e.target.id==='maintenanceToggle'){const next=e.target.getAttribute('aria-checked')!=='true';e.target.setAttribute('aria-checked',String(next));e.target.classList.toggle('on',next);document.getElementById('maintenanceValue').value=String(next)}
});
document.addEventListener('change',e=>{if(e.target.id==='dbEngine'){const examples={sqlite:'sqlite:///E:/data/project.sqlite3',postgresql:'postgresql+psycopg://user:password@localhost:5432/mydb',mysql:'mysql+pymysql://user:password@localhost:3306/mydb',mssql:'mssql+pyodbc://user:password@localhost/mydb?driver=ODBC+Driver+18+for+SQL+Server'};document.getElementById('dbUrl').placeholder=examples[e.target.value]}});
document.addEventListener('input',e=>{if(e.target.id==='maintenanceMessage'){const p=document.getElementById('previewMessage');if(p)p.textContent=e.target.value}});
document.addEventListener('submit',async e=>{
 e.preventDefault();const form=e.target;if(!form.id)return;const data=Object.fromEntries(new FormData(form));const submit=form.querySelector('[type="submit"]');if(submit)submit.disabled=true;
 try{
  switch(form.id){
   case 'loginForm':{const d=await api('/login',{method:'POST',body:JSON.stringify(data)});state.user=d.user;state.csrf=d.csrf;const me=await api('/me');state.permissions=me.permissions;state.version=me.version;renderShell();await loadPage();break;}
   case 'passwordForm':{if(data.new_password!==data.confirm_password)throw new Error('The new passwords do not match');const result=await api('/password',{method:'POST',body:JSON.stringify({current_password:data.current_password,new_password:data.new_password,email:data.email})});state.user=null;state.csrf='';closeModal();renderLogin();toast(result.verification_sent?'Password changed. Check your email for a verification link.':'Password changed. Sign in again. Configure SMTP to verify your recovery address.');break;}
   case 'forgotForm':{const r=await api('/forgot-password',{method:'POST',body:JSON.stringify({email:data.email})});form.replaceWith(document.createElement('div'));toast(r.message);const box=document.querySelector('.login-card p');if(box)box.textContent=r.message;break;}
   case 'verifyForm':{await api('/verify-email',{method:'POST',body:JSON.stringify({token:data.token})});history.replaceState({},'', '/admin');renderLogin();toast('Email verified! You can now use password recovery.');break;}
   case 'resetLinkForm':{if(data.new_password!==data.confirm_password)throw new Error('Passwords do not match');await api('/reset-password',{method:'POST',body:JSON.stringify({token:data.token,new_password:data.new_password})});history.replaceState({},'', '/admin');renderLogin();toast('Password reset. Sign in with your new password.');break;}
   case 'newUserForm':await api('/users',{method:'POST',body:JSON.stringify({...data,role_id:Number(data.role_id)})});closeModal();toast('Administrator created');await loadPage('users');break;
   case 'editUserForm':await api(`/users/${Number(form.dataset.id)}`,{method:'PATCH',body:JSON.stringify({display_name:data.display_name,role_id:Number(data.role_id)})});closeModal();toast('Administrator updated');await loadPage('users');break;
   case 'resetUserForm':await api(`/users/${Number(form.dataset.id)}/reset-password`,{method:'POST',body:JSON.stringify(data)});closeModal();toast('Temporary password set');await loadPage('users');break;
   case 'newAppUserForm':await api('/app-users',{method:'POST',body:JSON.stringify(data)});closeModal();toast('Application account created');await loadPage('app-users');break;
   case 'appUserPasswordForm':await api(`/app-users/${Number(form.dataset.id)}/reset-password`,{method:'POST',body:JSON.stringify(data)});closeModal();toast('Password reset; user sessions revoked');await loadPage('app-users');break;
   case 'newRoleForm':await api('/roles',{method:'POST',body:JSON.stringify({...data,permissions:[]})});closeModal();toast('Role created');await loadPage('roles');break;
   case 'newDatabaseForm':await api('/databases',{method:'POST',body:JSON.stringify(data)});closeModal();toast('Connection added');await loadPage('databases');break;
   case 'maintenanceForm':{const changes={maintenance_enabled:data.maintenance_enabled==='true',maintenance_message:data.maintenance_message,maintenance_start:data.maintenance_start?new Date(data.maintenance_start).toISOString():'',maintenance_end:data.maintenance_end?new Date(data.maintenance_end).toISOString():''};await api('/settings',{method:'PUT',body:JSON.stringify(changes)});toast('Maintenance settings saved');await loadPage('maintenance');break;}
   case 'hostingForm':{const result=await api('/hosting',{method:'PUT',body:JSON.stringify({port:Number(data.port),mode:data.mode})});toast(result.restart_required?'Settings saved — restart AI App Server to apply them':'Settings saved');await loadPage('service');break;}
   case 'settingsForm':await api('/settings',{method:'PUT',body:JSON.stringify(data)});toast('Settings saved');await loadPage('settings');break;
  }
 }catch(err){toast(err.message,true)}finally{if(submit)submit.disabled=false}
});
(async()=>{if(showRecoveryRoute())return;root.innerHTML='<div class="loading"><div class="spinner"></div></div>';try{const me=await api('/me');state.user=me.user;state.csrf=me.csrf;state.permissions=me.permissions;state.version=me.version;renderShell();await loadPage()}catch(e){renderLogin()}})();
