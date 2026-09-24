import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,value,calcNbar,ITEM}=M;
Object.assign(M.CAL, CANON);
calcNbar();
const DEX=JSON.parse(fs.readFileSync('raw2/dex2.json','utf8'));
const N=D.length;
const isStone=k=>/나이트([XYZ])?$/.test(k);
/* 원본 아이템명 → 모델 클래스 */
const PLATE=["검은안경","신비의물방울","녹지않는얼음","기적의씨","실크스카프","목탄","자석","휘어진스푼",
  "검은띠","부드러운모래","딱딱한돌","예리한부리","용의이빨","금속코트","은빛가루","요정의깃털","저주의부적",
  "독바늘","이상한부적","날카로운부리"];
const CLS={"생명의구슬":1,"구애스카프":2,"기합의띠":3,"자뭉열매":4,"먹다남은음식":5,"달인의띠":6,
  "울퉁불퉁멧":8,"풍선":9};
for(const p of PLATE) CLS[p]=7;
const clsOf=n=>isStone(n)?-1:(CLS[n]??0);
/* 집계 */
const agg={};
for(const [ko,r] of Object.entries(DEX)) for(const [it,v] of Object.entries(r.item||{})){
  if(isStone(it))continue; if(!agg[it])agg[it]=[0,0]; agg[it][0]+=v; if(v>=10)agg[it][1]++;
}
const AGG=Object.entries(agg).sort((a,b)=>b[1][0]-a[1][0]).slice(0,24)
  .map(([n,[s,c]])=>[n,+(s/N).toFixed(2),c,clsOf(n)]);
/* 개체별 상위 아이템(스톤 제외) + 상대 가정 아이템 */
const IUSE={}, OPPIT=[], IUSEC=[], STONEP=[];
D.forEach((m,i)=>{
  const all=Object.entries(DEX[m.ko]?.item||{});
  const stone=all.filter(([k])=>isStone(k)).reduce((a,[,v])=>a+v,0);
  const raw=all.filter(([k])=>!isStone(k)).sort((a,b)=>b[1]-a[1]);
  const sum=raw.reduce((a,[,v])=>a+v,0)||1;
  IUSE[m.ko]=raw.slice(0,4).map(([k,v])=>[k,+v.toFixed(1),clsOf(k)]);
  OPPIT[i]= raw.length? clsOf(raw[0][0]) : 0;
  STONEP[i]=+stone.toFixed(1);
  const cv=new Array(ITEM.length).fill(0);
  for(const [k,v] of raw) cv[clsOf(k)]+=v/sum;      // 스톤을 뺀 나머지 안에서의 점유율
  IUSEC.push(cv.map(x=>+x.toFixed(4)));
});
/* 행렬 */
const enc=Ms=>Ms.map(r=>r.map(v=>{
  const i=Math.round(Math.max(-1,Math.min(1,v))*20)+20;
  return String.fromCharCode(i<26?65+i:71+i);}).join('')).join('');
const VOPP=[], IABS={}, IDLT={};
for(let i=0;i<N;i++){const row=[];for(let j=0;j<N;j++)row.push(value(i,j,0,0,0,OPPIT[j]));VOPP.push(row);}
let report=[];
for(let c=1;c<ITEM.length;c++){
  /* 차분이 아니라 '그 아이템을 들었을 때의 값' 자체를 저장한다 —
     차분은 ±1.4까지 벌어져 [-1,1] 인코딩에서 잘린다. */
  const Ab=[],Dl=[];let nz=0,sum=0,mxv=0;
  for(let i=0;i<N;i++){const ra=[],rd=[];
    for(let j=0;j<N;j++){const v=value(i,j,0,0,c,OPPIT[j]);const d=v-VOPP[i][j];
      ra.push(v);rd.push(d);if(Math.abs(d)>1e-9){nz++;sum+=d;mxv=Math.max(mxv,Math.abs(d))}}
    Ab.push(ra);Dl.push(rd);}
  IABS[c]=Ab; IDLT[c]=Dl;
  report.push([ITEM[c].n, (nz/(N*N)*100).toFixed(1)+'%', (sum/(N*N)).toFixed(4), mxv.toFixed(2)]);
}
/* 개체 × 아이템 평균 가치 (등장 빈도 가중) */
const FREQ=JSON.parse(fs.readFileSync('opps100.json','utf8')).flat();
const cnt=new Array(N).fill(0); for(const x of FREQ) cnt[x]++;
const W=cnt.map(c=>c+1), SW=W.reduce((a,b)=>a+b,0);
const IVAL=D.map((m,i)=>{
  const r=[0];
  for(let c=1;c<ITEM.length;c++){let s=0;for(let j=0;j<N;j++){if(i===j)continue;s+=IDLT[c][i][j]*W[j]}r.push(+(s/(SW-W[i])).toFixed(4));}
  return r;
});
fs.writeFileSync('item_blocks.json',JSON.stringify({
  ITEMDEF:ITEM.map(x=>x.n), AGG, IUSE, OPPIT, IUSEC, STONEP,
  VOPP:enc(VOPP), IVIT:Object.fromEntries(Object.entries(IABS).map(([c,m])=>[c,enc(m)])), IVAL
}));
console.log('아이템 클래스별 영향  (0이 아닌 칸 비율 / 평균 Δ / 최대 |Δ|)');
report.forEach(r=>console.log('  '+r[0].padEnd(8)+r[1].padStart(7)+r[2].padStart(10)+r[3].padStart(7)));
console.log('\n상대 가정 아이템 분포:');
const dist={};OPPIT.forEach(c=>dist[ITEM[c].n]=(dist[ITEM[c].n]||0)+1);
console.log('  '+Object.entries(dist).sort((a,b)=>b[1]-a[1]).map(([k,v])=>k+' '+v).join(', '));
console.log('\n아이템 가치 상위 (개체, 최고 아이템, Δ):');
IVAL.map((r,i)=>{const b=r.indexOf(Math.max(...r));return [D[i].ko,ITEM[b].n,r[b]]})
  .sort((a,b)=>b[2]-a[2]).slice(0,12).forEach(r=>console.log('  '+r[0].padEnd(14)+r[1].padEnd(9)+(r[2]>=0?'+':'')+r[2]));
