/* 상대 메가를 반영한 후보 탐색 — 상대 팀도 한 경기 메가 1회이므로
   종별 '실효 메가 확률'(스톤 채택률을 같은 팀 스톤 보유자 수로 나눈 값, 래더 표본 평균)로 가중한다. */
import fs from 'fs';
const D=JSON.parse(fs.readFileSync('data100.json','utf8'));
const V=JSON.parse(fs.readFileSync('V100.json','utf8'));
const VM=JSON.parse(fs.readFileSync('V100m.json','utf8'));
const VO=JSON.parse(fs.readFileSync('V100o.json','utf8'));
const VMM=JSON.parse(fs.readFileSync('V100mm.json','utf8'));
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const E=JSON.parse(fs.readFileSync('effmega.json','utf8'));
const MG=JSON.parse(fs.readFileSync('mega.json','utf8'));
const POOL=process.argv[2]||'full';
const OBS=JSON.parse(fs.readFileSync('opps100.json','utf8')).filter(o=>o.length>=4&&o.length<=6);
const obsc=new Array(100).fill(0); OBS.forEach(o=>o.forEach(i=>obsc[i]++));
const inPool=i=>POOL==='full'?true:POOL==='obs'?obsc[i]>=5:D[i].rank<=+POOL;
const IDX=[...Array(100).keys()].filter(inPool);
const NC=IDX.length,NO=100,KEEP=600;
const stone=IDX.map(i=>MG[D[i].ko]?1:0);
const B0=IDX.map(i=>{const a=new Float32Array(NO);for(let j=0;j<NO;j++)a[j]=(1-E[j])*V[i][j]+E[j]*VO[i][j];return a});
const B1=IDX.map((i,k)=>{if(!stone[k])return null;const a=new Float32Array(NO);for(let j=0;j<NO;j++)a[j]=(1-E[j])*VM[i][j]+E[j]*VMM[i][j];return a});
const R=IDX.map((i,k)=>{const a=new Float32Array(NO);for(let j=0;j<NO;j++)a[j]=stone[k]?Math.max(B0[k][j],B1[k][j]):B0[k][j];return a});
const Wf=new Float32Array(W);
const t1=[],t2=[];for(let d=0;d<7;d++){t1.push(new Float32Array(NO));t2.push(new Float32Array(NO))}
t1[0].fill(-9);t2[0].fill(-9);
const heaps=[[],[],[]],worst=[-9,-9,-9];
function push(k,sc,team){const h=heaps[k];
  if(h.length<KEEP){h.push({sc,team:Array.from(team)});if(h.length===KEEP){h.sort((a,b)=>a.sc-b.sc);worst[k]=h[0].sc}}
  else if(sc>worst[k]){h[0]={sc,team:Array.from(team)};h.sort((a,b)=>a.sc-b.sc);worst[k]=h[0].sc}}
const team=new Int32Array(6);let count=0;
function rec(depth,start,stones){
  if(depth===6){let s=0;const A=t1[6],B=t2[6];for(let j=0;j<NO;j++)s+=Wf[j]*(A[j]+B[j]);count++;push(stones,s*0.5,team);return}
  const need=6-depth;
  for(let k=start;k<=NC-need;k++){const ns=stones+stone[k];if(ns>2)continue;
    const r=R[k],a0=t1[depth],b0=t2[depth],a1=t1[depth+1],b1=t2[depth+1];
    for(let j=0;j<NO;j++){const v=r[j];if(v>a0[j]){a1[j]=v;b1[j]=a0[j]}else{a1[j]=a0[j];b1[j]=v>b0[j]?v:b0[j]}}
    team[depth]=k;rec(depth+1,k+1,ns)}}
rec(0,0,0);
function proxy1(t,mk){let s=0;
  for(let j=0;j<NO;j++){let a=-9,b=-9;
    for(const k of t){const q=(k===mk?B1[k]:B0[k])[j];if(q>a){b=a;a=q}else if(q>b)b=q}
    s+=W[j]*(a+b)*0.5}return s}
function rescore(t){let best=proxy1(t,-1);for(const k of t)if(stone[k])best=Math.max(best,proxy1(t,k));return best}
const out=[];
heaps.forEach((h,k)=>{const re=h.map(x=>({sc:rescore(x.team),team:x.team}));re.sort((a,b)=>b.sc-a.sc);
  re.slice(0,150).forEach(x=>out.push({sc:+x.sc.toFixed(4),stones:k,team:x.team.map(kk=>D[IDX[kk]].ko)}))});
const OUTF={'full':'cand_full.json','obs':'cand_obs.json','50':'cand100.json'}[POOL]||('cand_'+POOL+'.json');
fs.writeFileSync(OUTF,JSON.stringify(out));
console.log(POOL,'풀',NC,'종 / 조합',count.toLocaleString());
heaps.forEach((h,k)=>console.log(` 스톤${k}장 최고 ${h[0].sc.toFixed(4)} — ${h[0].team.map(kk=>D[IDX[kk]].ko).join('/')}`));
