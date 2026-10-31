const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
let stylistId=null, selectedTime=null, lang="uz";
const $=id=>document.getElementById(id), dateInput=$("date");
const stylists=window.HAWK_STYLISTS||[], certificates=window.HAWK_CERTIFICATES||[];
const today=new Date(), localToday=new Date(today.getTime()-today.getTimezoneOffset()*60000).toISOString().slice(0,10);
dateInput.min=localToday; dateInput.value=localToday;
const requestedService = new URLSearchParams(window.location.search).get("service");

function staticUrl(path){return path?`/static/${String(path).replace(/^\/+/,"")}`:"";}
function addText(parent,tag,className,text){const el=document.createElement(tag);if(className)el.className=className;el.textContent=text||"";parent.appendChild(el);return el;}
function setLanguage(next) {
  lang=next; document.documentElement.lang=lang;
  document.querySelectorAll("[data-uz][data-ru]").forEach(el=>el.textContent=el.dataset[lang]);
  $("lang-toggle").textContent=lang==="uz"?"РУССКИЙ":"O‘ZBEKCHA";
  const service=$("service"), current=service.value;
  [...service.options].forEach(o=>{
    if(!o.value)return;
    const title=lang==="ru"?(o.dataset.nameRu||o.dataset.nameUz):o.dataset.nameUz;
    const price=(o.dataset.price||"");
    const duration=(o.dataset.duration||"");
    o.textContent=`${title} — ${Number(price).toLocaleString("ru-RU")} so‘m (${duration} min)`;
  });
  service.value=current;
}
$("lang-toggle").addEventListener("click",()=>setLanguage(lang==="uz"?"ru":"uz"));

function renderProfile(stylist){
  const panel=$("stylist-profile"), content=$("profile-content"), certArea=$("certificate-area");
  content.replaceChildren();certArea.replaceChildren();
  const row=document.createElement("div");row.className="profile-main";
  if(stylist.photo){const img=document.createElement("img");img.className="profile-photo";img.src=staticUrl(stylist.photo);img.alt=stylist.name;row.appendChild(img);}
  const info=addText(row,"div","profile-info","");
  addText(info,"h3","",stylist.name);
  if(stylist.title)addText(info,"p","profile-title",stylist.title);
  if(stylist.experience)addText(info,"p","profile-meta",`Tajriba: ${stylist.experience}`);
  if(stylist.bio)addText(info,"p","profile-bio",stylist.bio);
  if(stylist.specialties)addText(info,"p","profile-meta",`Mutaxassisliklar: ${stylist.specialties}`);
  content.appendChild(row);
  const ownCertificates=certificates.filter(c=>Number(c.stylist_id)===Number(stylist.id));
  if(ownCertificates.length){
    addText(certArea,"h3","subsection-title",lang==="uz"?"Sertifikatlar":"Сертификаты");
    const grid=addText(certArea,"div","certificate-gallery","");
    ownCertificates.forEach(cert=>{const card=addText(grid,"div","certificate-card","");if(cert.photo){const img=document.createElement("img");img.src=staticUrl(cert.photo);img.alt=cert.title||"Sertifikat";card.appendChild(img);}addText(card,"span","",cert.title);});
  }
  panel.classList.remove("hidden");
}
function filterServices(){
  const service=$("service"), gallery=$("service-gallery");gallery.replaceChildren();let available=[];
  [...service.options].forEach(o=>{
    if(!o.value)return;
    const visible=Number(o.dataset.stylist)===stylistId;
    o.hidden=!visible;o.disabled=!visible;
    if(visible)available.push(o);
  });
  service.disabled=!stylistId||!available.length;
  if(!available.length){service.value="";addText(gallery,"p","muted",lang==="uz"?"Bu sartaroshda hozircha xizmat yo‘q.":"У мастера пока нет услуг.");return;}
  const requested=available.find(o=>o.value===requestedService);
  service.value=(requested||available[0]).value;
  available.forEach(o=>{
    const card=document.createElement("button");card.type="button";card.className="service-card";
    card.classList.toggle("selected-service",o.value===service.value);
    if(o.dataset.photo){const img=document.createElement("img");img.src=staticUrl(o.dataset.photo);img.alt=o.dataset.nameUz;card.appendChild(img);}
    const body=addText(card,"span","service-card-body","");
    addText(body,"strong","",lang==="ru"?(o.dataset.nameRu||o.dataset.nameUz):o.dataset.nameUz);
    addText(body,"span","service-description",o.dataset.description||"");
    addText(body,"span","service-price",`${Number(o.dataset.price).toLocaleString("ru-RU")} so‘m`);
addText(body,"span","service-description",`${lang==="uz"?"Davomiyligi: ":"Длительность: "}${o.dataset.duration} daqiqa`);
    card.addEventListener("click",()=>{service.value=o.value;gallery.querySelectorAll(".service-card").forEach(c=>c.classList.remove("selected-service"));card.classList.add("selected-service");});
    gallery.appendChild(card);
  });
}
document.querySelectorAll(".stylist-card").forEach(card=>card.addEventListener("click",()=>{
  document.querySelectorAll(".stylist-card").forEach(c=>c.classList.remove("active"));
  card.classList.add("active");stylistId=Number(card.dataset.id);
  const stylist=stylists.find(s=>Number(s.id)===stylistId);if(stylist)renderProfile(stylist);
  filterServices();
  $("selected-stylist").textContent=(lang==="uz"?"Tanlandi: ":"Выбран: ")+card.dataset.name;
  $("booking").classList.remove("hidden");loadSlots();
  $("stylist-profile").scrollIntoView({behavior:"smooth",block:"start"});
}));
dateInput.addEventListener("change",loadSlots);
$("service").addEventListener("change", loadSlots);
async function loadSlots(){
  selectedTime=null;$("slots").innerHTML=`<p class="muted">${lang==="uz"?"Yuklanmoqda...":"Загрузка..."}</p>`;
  if(!stylistId||!dateInput.value)return;
  try{const serviceId = Number($("service").value);
const r = await fetch(`/api/slots?stylist_id=${stylistId}&date=${dateInput.value}&service_id=${serviceId}`), d = await r.json();$("slots").replaceChildren();
    if(!d.slots?.length){addText($("slots"),"p","muted",lang==="uz"?"Bo‘sh vaqt qolmagan.":"Свободного времени нет.");return;}
    d.slots.forEach(t=>{const b=document.createElement("button");b.type="button";b.className="slot";b.textContent=t;
      b.onclick=()=>{document.querySelectorAll(".slot").forEach(x=>x.classList.remove("chosen"));b.classList.add("chosen");selectedTime=t;};$("slots").appendChild(b);});
  }catch(e){$("slots").textContent=lang==="uz"?"Vaqtlarni yuklashda xatolik.":"Ошибка загрузки времени.";}
}
$("submit").addEventListener("click",async()=>{
  const notice=$("notice");notice.textContent="";
  if(!stylistId||!selectedTime||!$("service").value){notice.textContent=lang==="uz"?"Mutaxassis, xizmat va vaqtni tanlang.":"Выберите мастера, услугу и время.";return;}
  const payload={stylist_id:stylistId,service_id:Number($("service").value),date:dateInput.value,time:selectedTime,
    name:$("name").value.trim(),phone:$("phone").value.trim(),init_data:tg?.initData||""};
  if(!payload.name||!payload.phone){notice.textContent=lang==="uz"?"Ism va telefonni kiriting.":"Введите имя и телефон.";return;}
  const btn=$("submit");btn.disabled=true;
  try{const r=await fetch("/api/book",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),d=await r.json();
    notice.textContent=d.message;notice.className="notice "+(d.ok?"success":"error");if(d.ok){selectedTime=null;await loadSlots();}
  }catch(e){notice.textContent=lang==="uz"?"Ulanishda xatolik.":"Ошибка соединения.";}
  finally{btn.disabled=false;}
});
