
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
let stylistId=null, selectedTime=null, lang="uz";
const $=id=>document.getElementById(id), dateInput=$("date");
const today=new Date(), localToday=new Date(today.getTime()-today.getTimezoneOffset()*60000).toISOString().slice(0,10);
dateInput.min=localToday; dateInput.value=localToday;
const requestedService = new URLSearchParams(window.location.search).get("service");
if (requestedService && $("service") && [...$("service").options].some(o=>o.value===requestedService)) {
  $("service").value = requestedService;
}


function setLanguage(next) {
  lang=next; document.documentElement.lang=lang;
  document.querySelectorAll("[data-uz][data-ru]").forEach(el=>el.textContent=el.dataset[lang]);
  $("lang-toggle").textContent=lang==="uz"?"РУССКИЙ":"O‘ZBEKCHA";
  const service=$("service"), current=service.value;
  [...service.options].forEach(o=>{
    const title=lang==="ru"?(o.dataset.nameRu||o.dataset.nameUz):o.dataset.nameUz;
    o.textContent=`${title} — ${Number(o.textContent.match(/[0-9][0-9,]*/)?.[0]?.replaceAll(",","")||0).toLocaleString("ru-RU")} so‘m`;
  });
  service.value=current;
}
$("lang-toggle").addEventListener("click",()=>setLanguage(lang==="uz"?"ru":"uz"));

document.querySelectorAll(".stylist-card").forEach(card=>card.addEventListener("click",()=>{
  document.querySelectorAll(".stylist-card").forEach(c=>c.classList.remove("active"));
  card.classList.add("active"); stylistId=Number(card.dataset.id);
  $("selected-stylist").textContent=(lang==="uz"?"Tanlandi: ":"Выбран: ")+card.dataset.name;
  $("booking").classList.remove("hidden"); loadSlots(); $("booking").scrollIntoView({behavior:"smooth"});
}));
dateInput.addEventListener("change",loadSlots);
async function loadSlots(){
  selectedTime=null; $("slots").innerHTML=`<p class="muted">${lang==="uz"?"Yuklanmoqda...":"Загрузка..."}</p>`;
  if(!stylistId||!dateInput.value)return;
  const r=await fetch(`/api/slots?stylist_id=${stylistId}&date=${dateInput.value}`),d=await r.json();
  $("slots").innerHTML="";
  if(!d.slots?.length){$("slots").innerHTML=`<p class="muted">${lang==="uz"?"Bo‘sh vaqt qolmagan.":"Свободного времени нет."}</p>`;return;}
  d.slots.forEach(t=>{const b=document.createElement("button");b.className="slot";b.textContent=t;
    b.onclick=()=>{document.querySelectorAll(".slot").forEach(x=>x.classList.remove("chosen"));b.classList.add("chosen");selectedTime=t;};
    $("slots").appendChild(b);});
}
$("submit").addEventListener("click",async()=>{
  const notice=$("notice");notice.textContent="";
  if(!stylistId||!selectedTime){notice.textContent=lang==="uz"?"Mutaxassis va vaqtni tanlang.":"Выберите мастера и время.";return;}
  const payload={stylist_id:stylistId,service_id:Number($("service").value),date:dateInput.value,time:selectedTime,
    name:$("name").value.trim(),phone:$("phone").value.trim(),init_data:tg?.initData||""};
  if(!payload.name||!payload.phone){notice.textContent=lang==="uz"?"Ism va telefonni kiriting.":"Введите имя и телефон.";return;}
  const btn=$("submit");btn.disabled=true;
  try{const r=await fetch("/api/book",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),d=await r.json();
    notice.textContent=d.message;notice.className="notice "+(d.ok?"success":"error");if(d.ok){selectedTime=null;await loadSlots();}
  }catch(e){notice.textContent=lang==="uz"?"Ulanishda xatolik.":"Ошибка соединения.";}
  finally{btn.disabled=false;}
});
