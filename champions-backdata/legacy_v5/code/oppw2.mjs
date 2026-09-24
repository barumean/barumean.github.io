import fs from 'fs';
const DATA=JSON.parse(fs.readFileSync('data100.json','utf8'));
const idx={}; DATA.forEach((d,i)=>idx[d.ko]=i);
// 표기 정규화
const ALIAS={
 "킬가르도 (실드폼)":"킬가르도","킬가르도 (블레이드폼)":"킬가르도",
 "에써르 (수컷의 모습)":"에써르(수컷)","에써르 (암컷의 모습)":"에써르(암컷)",
 "대쓰여너 (수컷의 모습)":"대쓰여너","대쓰여너 (암컷의 모습)":null,
 "찌르호크 (암컷)":"찌르호크","번치코 (암컷)":"번치코","화염레오 (암컷)":"화염레오",
 "조로아크":"조로아크(히스이)","미끄래곤":"미끄래곤(히스이)","윈디":"윈디(히스이)",
 "야도킹":"가라르야도킹","알로라 나인테일":"알로라 나인테일",
 "스트린더 (하이한 모습)":"스트린더(하이)","스트린더 (로우한 모습)":"스트린더(로우)",
};
function norm(raw){
  const n=raw.trim();
  const try1=x=>{ if(x in ALIAS) return ALIAS[x]; if(idx[x]!==undefined) return x; return undefined };
  let r=try1(n); if(r!==undefined) return r;              // 메가니움처럼 '메가'로 시작하는 본명 먼저
  r=try1(n.replace(/^메가/,'').replace(/[XYZ]$/,'')); if(r!==undefined) return r;   // 메가폼 → 기본형
  r=try1(n.replace(/\s*\(.*\)\s*/,'').trim()); if(r!==undefined) return r;
  r=try1(n.replace(/^메가/,'').replace(/[XYZ]$/,'').replace(/\s*\(.*\)\s*/,'').trim()); if(r!==undefined) return r;
  return null;
}
const lines=fs.readFileSync('raw2/teams2.txt','utf8').trim().split('\n');
const seen=new Set(), opps=[], unknown={};
let dropped=0;
for(const L of lines){
  const key=L.trim(); if(seen.has(key)){dropped++;continue} seen.add(key);
  const members=L.split(',').map(s=>s.trim()).filter(Boolean);
  const ids=[];
  for(const m of members){ const n=norm(m);
    if(n===null||idx[n]===undefined){ unknown[m]=(unknown[m]||0)+1; continue }
    if(!ids.includes(idx[n])) ids.push(idx[n]); }
  if(ids.length>=4) opps.push(ids);
}
// 조우 빈도 → 가중치. 표본에 없는 개체는 순위 감쇠로 채운다.
const cnt=new Array(100).fill(0);
opps.forEach(o=>o.forEach(i=>cnt[i]++));
const seenIdx=cnt.map((c,i)=>c>0?i:-1).filter(i=>i>=0);
// w ∝ (rank+5)^-a 를 관측 개체에 맞춰 최소제곱 적합
const xs=seenIdx.map(i=>Math.log(DATA[i].rank+5)), ys=seenIdx.map(i=>Math.log(cnt[i]/opps.length));
const mx=xs.reduce((a,b)=>a+b,0)/xs.length, my=ys.reduce((a,b)=>a+b,0)/ys.length;
let num=0,den=0; for(let k=0;k<xs.length;k++){num+=(xs[k]-mx)*(ys[k]-my);den+=(xs[k]-mx)**2}
const a=num/den, b=my-a*mx;
const W=cnt.map((c,i)=> c>0 ? c/opps.length : Math.exp(b)*Math.pow(DATA[i].rank+5,a));
const sum=W.reduce((x,y)=>x+y,0); const Wn=W.map(x=>x/sum*100);
fs.writeFileSync('opps100.json',JSON.stringify(opps));
fs.writeFileSync('oppw100.json',JSON.stringify(Wn));
console.log('원본',lines.length,'행 / 중복제거',dropped,'/ 사용 팀',opps.length);
console.log('감쇠 지수 a =',a.toFixed(3));
console.log('표본에 등장한 개체',seenIdx.length,'/100');
const uk=Object.entries(unknown).sort((x,y)=>y[1]-x[1]);
console.log('100위 밖 이름('+uk.length+'종, 총 '+uk.reduce((s,x)=>s+x[1],0)+'회):',uk.slice(0,12).map(x=>x[0]+'×'+x[1]).join(', '));
const top=[...Wn.keys()].sort((p,q)=>Wn[q]-Wn[p]).slice(0,12);
console.log('조우 빈도 상위:',top.map(i=>DATA[i].ko+' '+Wn[i].toFixed(1)+'%').join(', '));
// 51~100위 조우 비중
const expShare=Wn.reduce((s,w,i)=>s+(DATA[i].rank>50?w:0),0);
console.log('51~100위 조우 비중:',expShare.toFixed(1)+'%');
