((root) => {
 'use strict';
 function validate(points, type) {
  if (!Array.isArray(points) || !points.length || points.length > 24) throw new Error('1~24개의 항목을 입력하세요.');
  const clean = points.map(p => ({label:String(p.label).trim().slice(0,200),value:Number(p.value)}));
  if (clean.some(p => !p.label || !Number.isFinite(p.value) || Math.abs(p.value)>1e15)) throw new Error('항목 이름과 유효한 숫자를 입력하세요.');
  if (type==='donut' && (clean.some(p=>p.value<0) || !clean.some(p=>p.value>0))) throw new Error('도넛 차트는 0 이상의 값과 양수 합계가 필요합니다.');
  return clean;
 }
 function parse(text, type) {
  return validate(text.trim().split('\n').filter(line=>line.trim()).map(line=>{
   const split=line.lastIndexOf(',');
   if(split<1 || !line.slice(split+1).trim())throw new Error('각 줄에 항목,숫자 형식으로 입력하세요.');
   return {label:line.slice(0,split),value:line.slice(split+1)};
  }),type);
 }
 const colors=['#4f46e5','#0891b2','#059669','#d97706','#db2777','#7c3aed'];
 function draw(canvas, points, {type,title,unit,color}) {
  points=validate(points,type);canvas.width=1280;canvas.height=720;
  const c=canvas.getContext('2d');if(!c)throw new Error('이 브라우저에서 차트를 만들 수 없습니다.');
  const number=v=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2}).format(v)+(unit?' '+unit:'');
  const label=s=>s.length>18?s.slice(0,17)+'…':s;
  c.fillStyle='#fff';c.fillRect(0,0,1280,720);
  c.fillStyle='#182238';c.font='600 36px "Noto Sans KR", sans-serif';c.fillText(title||'통계 인포그래픽',48,64);
  c.font='22px "Noto Sans KR", sans-serif';
  const low=Math.min(0,...points.map(p=>p.value)),high=Math.max(0,...points.map(p=>p.value)),range=high-low||1;
  if(type==='kpi'){
   const total=points.reduce((sum,p)=>sum+p.value,0);
   c.fillStyle=color;c.font='700 90px "Noto Sans KR", sans-serif';c.fillText(number(total),64,320,1152);
   c.fillStyle='#64748b';c.font='28px "Noto Sans KR", sans-serif';c.fillText(`${points.length}개 항목 합계`,64,390);
  }else if(type==='donut'){
   const total=points.reduce((sum,p)=>sum+p.value,0);let angle=-Math.PI/2;
   points.forEach((p,i)=>{const next=angle+p.value/total*Math.PI*2;c.beginPath();c.moveTo(350,400);c.arc(350,400,235,angle,next);c.closePath();c.fillStyle=i===0?color:colors[i%colors.length];c.fill();angle=next;
    const y=140+i*22;c.fillRect(690,y-15,14,14);c.fillStyle='#182238';c.font='19px "Noto Sans KR", sans-serif';c.fillText(`${label(p.label)}  ${number(p.value)} (${(p.value/total*100).toFixed(1)}%)`,720,y,500);
   });
   c.beginPath();c.arc(350,400,140,0,Math.PI*2);c.fillStyle='#fff';c.fill();c.fillStyle='#182238';c.font='600 30px "Noto Sans KR", sans-serif';c.textAlign='center';c.fillText(number(total),350,410,255);c.textAlign='left';
  }else if(type==='line'){
   const y=v=>620-(v-low)/range*470,x=i=>100+i*1050/Math.max(1,points.length-1);
   c.strokeStyle='#e0e6f0';c.lineWidth=2;c.beginPath();c.moveTo(100,150);c.lineTo(100,620);c.lineTo(1190,620);c.stroke();
   c.strokeStyle=color;c.lineWidth=5;c.beginPath();points.forEach((p,i)=>i?c.lineTo(x(i),y(p.value)):c.moveTo(x(i),y(p.value)));c.stroke();
   points.forEach((p,i)=>{c.fillStyle=color;c.beginPath();c.arc(x(i),y(p.value),6,0,Math.PI*2);c.fill();c.fillStyle='#182238';c.font='18px "Noto Sans KR", sans-serif';c.textAlign='center';c.fillText(number(p.value),x(i),y(p.value)-15,100);if(points.length<=12||i%Math.ceil(points.length/12)===0)c.fillText(label(p.label),x(i),660,90);});c.textAlign='left';
  }else{
   const x=v=>300+(v-low)/range*740,zero=x(0),step=540/points.length;
   c.strokeStyle='#cbd5e1';c.lineWidth=1;c.beginPath();c.moveTo(zero,120);c.lineTo(zero,670);c.stroke();
   points.forEach((p,i)=>{const y=130+i*step;c.fillStyle='#182238';c.font=`${Math.min(24,step*.65)}px "Noto Sans KR", sans-serif`;c.fillText(label(p.label),48,y+step*.55,235);c.fillStyle=color;c.fillRect(Math.min(zero,x(p.value)),y,Math.abs(x(p.value)-zero),step*.65);c.fillStyle='#182238';c.fillText(number(p.value),1060,y+step*.55,172);});
  }
  return points;
 }
 if(typeof module!=='undefined'&&module.exports){module.exports={parse,validate,draw};return;}
 root.initReportInfographics = function(context) {
  const $=id=>document.getElementById(id),panel=$('infographic-panel');if(!panel)return;
  let generation=0,ready=null;
  function datasets(){
   const select=$('infographic-dataset'),old=select.value;select.replaceChildren();
   for(const ds of context.datasets()){const option=document.createElement('option');option.value=ds.dataset_id;option.textContent=ds.label||ds.alias;select.append(option);}
   if([...select.options].some(o=>o.value===old))select.value=old;
   fields();
  }
  function fields(){
   const ds=context.datasets().find(d=>d.dataset_id===$('infographic-dataset').value);
   for(const [id,numeric] of [['infographic-label',false],['infographic-value',true]]){
    const select=$(id),old=select.value;select.replaceChildren();
    if(numeric){const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='수치 필드를 선택하세요';select.append(placeholder);}
    for(const f of ds?.fields||[]){if(numeric&&!['number','integer','decimal','string'].includes(f.type))continue;const option=document.createElement('option');option.value=f.field_id;option.textContent=(f.label||f.alias||f.field_id)+(numeric&&f.type==='string'?' (문자열 → 숫자변환)':'');select.append(option);}
    if([...select.options].some(o=>o.value===old))select.value=old;
    if(numeric&&!select.value){const first=ds?.fields?.find(f=>['number','integer','decimal'].includes(f.type));if(first)select.value=first.field_id;}
   }
   $('infographic-field-help').textContent=!ds?'데이터 탭에서 연결과 테이블을 선택하고 데이터셋을 추가하세요.':!ds.fields.some(f=>['number','integer','decimal','string'].includes(f.type))?'수치로 사용할 필드가 없습니다. 숫자 또는 문자열 필드가 있는 데이터셋을 선택하세요.':'문자열 필드는 선택 시 숫자로 변환합니다. 숫자만 입력된 열을 선택하세요 (예: 1200, 12.5).';
  }
  function invalidate(){++generation;ready=null;$('infographic-insert').disabled=true;$('infographic-preview').hidden=true;}
  panel.addEventListener('input',invalidate);
  $('infographic-dataset').addEventListener('change',fields);
  $('infographic-source').addEventListener('change',()=>{$('infographic-manual').hidden=$('infographic-source').value!=='manual';$('infographic-data').hidden=$('infographic-source').value!=='dataset';datasets();});
  document.querySelector('[data-panel="infographic"]').addEventListener('click',datasets);
  $('infographic-generate').onclick=async()=>{
   invalidate();const current=generation,button=$('infographic-generate');button.disabled=true;
   $('infographic-status').textContent='차트를 만드는 중…';
   try{
    const config={type:$('infographic-type').value,title:$('infographic-title').value,unit:$('infographic-unit').value,color:$('infographic-color').value};
    let points;
    if($('infographic-source').value==='manual')points=parse($('infographic-values').value,config.type);
    else{
     const parameters=JSON.parse($('infographic-parameters').value||'{}');
     if(!parameters||Array.isArray(parameters)||typeof parameters!=='object')throw new Error('보고서 입력값은 JSON 객체로 입력하세요.');
     const ds=context.datasets().find(d=>d.dataset_id===$('infographic-dataset').value),valueField=ds?.fields.find(f=>f.field_id===$('infographic-value').value);
     if(!ds||!$('infographic-label').value||!valueField)throw new Error('데이터셋, 항목 필드, 수치 필드를 선택하세요.');
     points=(await context.data({value_conversion:valueField.type==='string'?'to_decimal':'identity',dataset_id:$('infographic-dataset').value,label_id:$('infographic-label').value,value_id:$('infographic-value').value,aggregation:$('infographic-aggregation').value,parameters})).points;
    }
    if(current!==generation)return;
    ready=draw($('infographic-preview'),points,config);
    $('infographic-preview').hidden=false;$('infographic-insert').disabled=false;$('infographic-status').textContent=`${ready.length}개 항목으로 생성했습니다. 캔버스에 추가하세요.`;
   }catch(error){if(current===generation)$('infographic-status').textContent=error.message;}
   finally{button.disabled=false;}
  };
  $('infographic-insert').onclick=async()=>{
   if(!ready)return;
   const button=$('infographic-insert');button.disabled=true;
   try{
    const blob=await new Promise(resolve=>$('infographic-preview').toBlob(resolve,'image/png'));
    if(!blob)throw new Error('이미지를 생성하지 못했습니다. 다시 시도하세요.');
    await context.insert(blob);$('infographic-status').textContent='인포그래픽을 캔버스에 추가했습니다. 보고서를 저장하세요.';
   }catch(error){$('infographic-status').textContent=error.message;}
   finally{button.disabled=!ready;}
  };
  datasets();
 };
})(globalThis);
