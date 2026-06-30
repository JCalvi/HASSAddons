let rows=[], sortKey="ip", asc=true, expandedKey="";
let setupDevices=[];
const $ = id => document.getElementById(id);

function esc(s){return String(s||"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));}
function ipVal(ip){return (ip||"999.999.999.999").split(".").map(x=>parseInt(x)||999);}
function cmp(a,b){if(sortKey==="ip"){let A=ipVal(a.ip),B=ipVal(b.ip);for(let i=0;i<4;i++)if(A[i]!==B[i])return A[i]-B[i];return 0;} if(sortKey==="rssi")return(parseInt(a.rssi)||-999)-(parseInt(b.rssi)||-999);return String(a[sortKey]||"").localeCompare(String(b[sortKey]||""));}
function sortBy(k){asc=sortKey===k?!asc:true;sortKey=k;render();}
function rssiClass(v){let n=parseInt(v);if(!n)return"";if(n>=-60)return"rssi-good";if(n>=-72)return"rssi-ok";return"rssi-bad";}
async function postJson(url,obj){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj||{})});const d=await r.json();if(!d.ok)throw new Error(d.error||"Request failed");return d;}
function setSetupOutput(obj){$("setupOutput").textContent=typeof obj==="string"?obj:JSON.stringify(obj,null,2);}
function deviceLabel(d){return `${d.type||"Host"} ${d.name?d.name+" ":""}${d.ip||""}`.trim();}
function showKeyInfo(key){if(!key){$("keyInfo").textContent="";return;}$("keyInfo").innerHTML=`SSH key: ${esc(key.exists?"created":"missing")} - ${esc(key.private_key||"")}<br>Public key:<br><code>${esc(key.public_key_text||"")}</code>`;}
function defaultDevice(type){return {type:type||"Host",name:"",ip:"",user:"root",password:"",ssh:"unknown",message:""};}

function setupPayload(includePasswords=true){
  return {
    devices: setupDevices.map(d=>({type:d.type,name:d.name,ip:d.ip,user:d.user,password:includePasswords?d.password:""})),
    piholes: setupDevices.filter(d=>d.type==="Pi-hole"&&d.ip).map(d=>d.ip),
    access_points: setupDevices.filter(d=>d.type==="OpenWrt AP"&&d.ip).map(d=>d.ip),
    ssh_key_path: $("sshKeyPathInput").value.trim()||"/config/ssh/id_ed25519"
  };
}

function updateDeviceFromRow(i){
  const row=document.querySelector(`tr[data-setup-index="${i}"]`);
  if(!row) return;
  setupDevices[i].type=row.querySelector(".dev-type").value;
  setupDevices[i].name=row.querySelector(".dev-name").value.trim();
  setupDevices[i].ip=row.querySelector(".dev-ip").value.trim();
  setupDevices[i].user=row.querySelector(".dev-user").value.trim()||"root";
  setupDevices[i].password=row.querySelector(".dev-password").value;
}
function updateAllSetupDevices(){setupDevices.forEach((_,i)=>updateDeviceFromRow(i));}
function statusChip(d){
  if(d.ssh==="ok") return `<span class="chip ok">OK</span>`;
  if(d.ssh==="fail") return `<span class="chip bad">Fail</span>`;
  if(d.ssh==="installing") return `<span class="chip wait">Installing</span>`;
  if(d.ssh==="testing") return `<span class="chip wait">Testing</span>`;
  return `<span class="chip unknown">Unknown</span>`;
}
function renderSetupDevices(){
  $("setupDevices").innerHTML=setupDevices.map((d,i)=>`
    <tr data-setup-index="${i}">
      <td><select class="dev-type"><option ${d.type==="Pi-hole"?"selected":""}>Pi-hole</option><option ${d.type==="OpenWrt AP"?"selected":""}>OpenWrt AP</option><option ${d.type==="Host"?"selected":""}>Host</option></select></td>
      <td><input class="dev-name" value="${esc(d.name)}" placeholder="optional"></td>
      <td><input class="dev-ip" value="${esc(d.ip)}" placeholder="192.168.1.x"></td>
      <td><input class="dev-user" value="${esc(d.user||"root")}" placeholder="root"></td>
      <td><input class="dev-password" type="password" value="${esc(d.password||"")}" placeholder="not saved"></td>
      <td class="ssh-status">${statusChip(d)}${d.message?`<small>${esc(d.message)}</small>`:""}</td>
      <td class="row-actions"><button class="secondary install-one" type="button">Install</button><button class="secondary test-one" type="button">Test</button><button class="danger remove-one" type="button">Remove</button></td>
    </tr>`).join("");
  document.querySelectorAll("#setupDevices tr").forEach(row=>{
    const i=parseInt(row.dataset.setupIndex);
    row.querySelectorAll("input,select").forEach(el=>el.addEventListener("input",()=>updateDeviceFromRow(i)));
    row.querySelector(".remove-one").addEventListener("click",e=>{e.preventDefault();setupDevices.splice(i,1);renderSetupDevices();});
    row.querySelector(".install-one").addEventListener("click",e=>{e.preventDefault();installOne(i).catch(err=>setSetupOutput(err.message));});
    row.querySelector(".test-one").addEventListener("click",e=>{e.preventDefault();testOne(i).catch(err=>setSetupOutput(err.message));});
  });
}
function mergeStatuses(results){
  (results||[]).forEach(r=>{
    const d=setupDevices.find(x=>x.ip===r.ip);
    if(!d) return;
    d.ssh=(r.ok&& (r.key_ok===undefined || r.key_ok))?"ok":"fail";
    d.message=r.ok?(r.host||"Key OK"):(r.error||"Failed");
    d.password="";
  });
  renderSetupDevices();
}

async function loadConfig(){
  try{
    const r=await fetch("/api/config?_="+Date.now(),{cache:"no-store"}); const d=await r.json(); if(!d.ok)throw new Error(d.error||"Config failed");
    const c=d.config||{};
    $("sshKeyPathInput").value=c.ssh_key_path||"/config/ssh/id_ed25519";
    setupDevices=(c.devices||[]).map(x=>({type:x.type||"Host",name:x.name||"",ip:x.ip||"",user:x.user||c.ssh_user||"root",password:"",ssh:"unknown",message:""}));
    if(!setupDevices.length){
      (c.piholes||[]).forEach(ip=>setupDevices.push({type:"Pi-hole",name:"",ip,user:c.ssh_user||"root",password:"",ssh:"unknown",message:""}));
      (c.access_points||[]).forEach(ip=>setupDevices.push({type:"OpenWrt AP",name:"",ip,user:c.ssh_user||"root",password:"",ssh:"unknown",message:""}));
    }
    renderSetupDevices(); showKeyInfo(d.key);
  }catch(e){setSetupOutput("Config load failed: "+e.message);}
}
async function saveConfig(){updateAllSetupDevices();setSetupOutput("Saving config...");const d=await postJson("/api/config",setupPayload(false));showKeyInfo(d.key);setSetupOutput("Config saved.");}
async function generateKey(){setSetupOutput("Generating SSH key...");await saveConfig();const d=await postJson("/api/ssh/generate",{});showKeyInfo(d.key);setSetupOutput("SSH key ready.");}
async function installAll(){updateAllSetupDevices();if(!setupDevices.some(d=>d.password)){setSetupOutput("Enter at least one device password first. Each password can be different.");return;}setupDevices.forEach(d=>{if(d.password)d.ssh="installing";});renderSetupDevices();setSetupOutput("Installing SSH keys...");const d=await postJson("/api/ssh/install_all",setupPayload(true));showKeyInfo(d.key);mergeStatuses(d.results);setSetupOutput(d.results);}
async function installOne(i){updateDeviceFromRow(i);const d=setupDevices[i];if(!d.password){setSetupOutput("Enter the password for "+deviceLabel(d));return;}d.ssh="installing";renderSetupDevices();const res=await postJson("/api/ssh/install_one",{...setupPayload(true),ip:d.ip});showKeyInfo(res.key);mergeStatuses(res.results);setSetupOutput(res.results);}
async function testAll(){updateAllSetupDevices();setSetupOutput("Testing SSH...");await saveConfig();setupDevices.forEach(d=>d.ssh="testing");renderSetupDevices();const d=await postJson("/api/ssh/test",setupPayload(false));mergeStatuses(d.results);setSetupOutput(d.results);}
async function testOne(i){updateDeviceFromRow(i);const d=setupDevices[i];d.ssh="testing";renderSetupDevices();await saveConfig();const res=await postJson("/api/ssh/test",{...setupPayload(false),devices:[{type:d.type,name:d.name,ip:d.ip,user:d.user}]});mergeStatuses(res.results);setSetupOutput(res.results);}

function fillFilters(){
  const conns=[...new Set(rows.map(x=>x.connection).filter(Boolean))].sort();
  const aps=[...new Set(rows.map(x=>x.ap).filter(Boolean))].sort();
  const c=$("connectionFilter"), a=$("apFilter"), cv=c.value, av=a.value;
  c.innerHTML='<option value="">All connections</option>'+conns.map(x=>`<option>${esc(x)}</option>`).join("");
  a.innerHTML='<option value="">All APs</option>'+aps.map(x=>`<option>${esc(x)}</option>`).join("");
  c.value=cv; a.value=av;
}
function detailHtml(x){return `<tr class="detail"><td colspan="9"><b>${esc(x.host||x.ip||x.mac||"Unknown device")}</b><div class="detail-grid"><div>IP</div><div>${esc(x.ip)}</div><div>Host</div><div>${esc(x.host)}</div><div>MAC</div><div>${esc(x.mac)}</div><div>Status</div><div>${esc(x.status)}</div><div>Connection</div><div>${esc(x.connection)}</div><div>AP</div><div>${esc(x.ap)}</div><div>Band</div><div>${esc(x.band)}</div><div>RSSI</div><div>${esc(x.rssi?x.rssi+" dBm":"")}</div><div>Ping</div><div>${esc(x.ping)}</div><div>TCP</div><div>${esc(x.tcp)}</div><div>Neighbour State</div><div>${esc(x.neighbour_state)}</div><div>Last Wi-Fi Event</div><div>${esc(x.wifi_last_event)}</div><div>Last Wi-Fi Seen</div><div>${esc(x.wifi_last_seen)}</div><div>Source</div><div>${esc(x.source)}</div></div></td></tr>`;}
function render(){
  let q=$("search").value.toLowerCase(), status=$("statusFilter").value, conn=$("connectionFilter").value, ap=$("apFilter").value;
  let out=rows.filter(x=>{let blob=Object.values(x).join(" ").toLowerCase();if(q&&!blob.includes(q))return false;if(status&&x.status!==status)return false;if(conn&&x.connection!==conn)return false;if(ap&&x.ap!==ap)return false;return true;}).sort((a,b)=>asc?cmp(a,b):-cmp(a,b));
  $("body").innerHTML=out.map(x=>{const key=`${x.ip}|${x.mac}`;const open=expandedKey===key;return `<tr class="mainrow" data-key="${esc(key)}"><td>${esc(x.ip)}</td><td>${esc(x.host)}</td><td>${esc(x.mac)}</td><td class="${esc(x.status)}">${esc(x.status)}</td><td>${esc(x.connection)}</td><td>${esc(x.ap)}</td><td>${esc(x.band)}</td><td class="${rssiClass(x.rssi)}">${esc(x.rssi)}</td><td>${esc(x.source)}</td></tr>${open?detailHtml(x):""}`;}).join("");
  document.querySelectorAll(".mainrow").forEach(row=>row.addEventListener("click",()=>{expandedKey=expandedKey===row.dataset.key?"":row.dataset.key;render();}));
  const online=rows.filter(x=>x.status==="online").length, idle=rows.filter(x=>x.status==="idle").length, offline=rows.filter(x=>x.status==="offline").length;
  const wifi=rows.filter(x=>x.status==="online"&&x.connection&&x.connection!=="Ethernet"&&x.connection!=="Tailscale").length;
  const wired=rows.filter(x=>x.status==="online"&&x.connection==="Ethernet").length;
  const tailscale=rows.filter(x=>x.status==="online"&&x.connection==="Tailscale").length;
  $("updated").textContent=`Updated ${new Date().toLocaleTimeString()} - ${out.length}/${rows.length} shown`;
  $("summary").textContent=`${rows.length} devices - ${online} online - ${idle} idle - ${offline} offline - Wi-Fi ${wifi} - Ethernet ${wired} - Tailscale ${tailscale}`;
}
async function load(){const btn=$("refreshBtn"); btn.disabled=true; btn.textContent="Refreshing..."; $("updated").textContent="Refreshing..."; try{const r=await fetch("/api/refresh?_="+Date.now(),{cache:"no-store"}); const data=await r.json(); if(!data.ok) throw new Error(data.error||"Refresh failed"); rows=data.devices||[]; fillFilters(); render();}catch(e){$("updated").textContent="Refresh failed: "+e.message;} btn.disabled=false; btn.textContent="Refresh";}

document.addEventListener("DOMContentLoaded",()=>{
  ["search","statusFilter","connectionFilter","apFilter"].forEach(id=>$(id).addEventListener("input",render));
  document.querySelectorAll("th[data-sort]").forEach(th=>th.addEventListener("click",()=>sortBy(th.dataset.sort)));
  $("refreshBtn").addEventListener("click",e=>{e.preventDefault();load();});
  $("saveConfigBtn").addEventListener("click",e=>{e.preventDefault();saveConfig().catch(err=>setSetupOutput(err.message));});
  $("generateKeyBtn").addEventListener("click",e=>{e.preventDefault();generateKey().catch(err=>setSetupOutput(err.message));});
  $("installAllBtn").addEventListener("click",e=>{e.preventDefault();installAll().catch(err=>setSetupOutput(err.message));});
  $("testSshBtn").addEventListener("click",e=>{e.preventDefault();testAll().catch(err=>setSetupOutput(err.message));});
  $("addPiholeBtn").addEventListener("click",e=>{e.preventDefault();setupDevices.push(defaultDevice("Pi-hole"));renderSetupDevices();});
  $("addApBtn").addEventListener("click",e=>{e.preventDefault();setupDevices.push(defaultDevice("OpenWrt AP"));renderSetupDevices();});
  function setSetupCollapsed(collapsed){const p=$("setupPanel");p.classList.toggle("collapsed", collapsed);$("toggleSetupBtn").textContent=collapsed?"Show":"Hide";localStorage.setItem("networkExplorerSetupCollapsed", collapsed?"1":"0");}
  $("toggleSetupBtn").addEventListener("click",e=>{e.preventDefault();setSetupCollapsed(!$("setupPanel").classList.contains("collapsed"));});
  $("settingsBtn").addEventListener("click",e=>{e.preventDefault();setSetupCollapsed(false);$("setupPanel").scrollIntoView({behavior:"smooth",block:"start"});});
  setSetupCollapsed(localStorage.getItem("networkExplorerSetupCollapsed")==="1");
  loadConfig();
});
