/* Run before CSS to prevent a theme flash. */
"use strict";
(() => {
const key="stock-probs.theme";
const media=matchMedia("(prefers-color-scheme: dark)");
let choice;
try {
const saved=localStorage.getItem(key);
if(saved==="light"||saved==="dark") choice=saved;
else if(saved!==null) localStorage.removeItem(key);
}catch(_){}
const apply=()=>document.documentElement.dataset.theme=choice||(media.matches?"dark":"light");
const sync=()=>document.querySelectorAll("[name=theme]").forEach(radio=>radio.checked=radio.value===(choice||"system"));
const setChoice=(value)=>{
choice=value==="system"?null:value;
try{choice?localStorage.setItem(key,choice):localStorage.removeItem(key)}catch(_){}
apply();
sync();
};
const handleChange=(event)=>{
const radio=event.target?.closest?.("[name=theme]");
if(!radio)return;
setChoice(radio.value);
};
const applyAssistantTheme=(event)=>{
const detail=event.detail;
if(!detail||typeof detail!=="object"||Array.isArray(detail))return;
const keys=Object.keys(detail);
if(keys.length!==1||keys[0]!=="theme")return;
if(detail.theme!=="light"&&detail.theme!=="dark"&&detail.theme!=="system")return;
setChoice(detail.theme);
};
const syncOpenedSettings=(event)=>{
if(event.target?.id==="settings-menu"&&event.newState==="open")sync();
};
apply();
document.addEventListener("change", handleChange);
window.addEventListener("signal-ledger:assistant-theme", applyAssistantTheme);
document.addEventListener("toggle", syncOpenedSettings, true);
const bind=()=>sync();
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded", bind, { once: true });
else bind();
media.addEventListener("change", () => { if (!choice) apply(); sync(); });
})();
