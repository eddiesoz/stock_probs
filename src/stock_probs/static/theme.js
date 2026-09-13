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
apply();
const bind=()=>{
sync();
document.querySelectorAll("[name=theme]").forEach(radio=>radio.addEventListener("change",()=>{
choice=radio.value==="system"?null:radio.value;
try{choice?localStorage.setItem(key,choice):localStorage.removeItem(key)}catch(_){}
apply();
}));
};
document.addEventListener("DOMContentLoaded", bind, { once: true });
media.addEventListener("change", () => { if (!choice) apply(); sync(); });
})();
