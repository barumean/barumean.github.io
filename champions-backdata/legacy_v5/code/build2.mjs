import fs from 'fs';
const DX=JSON.parse(fs.readFileSync('raw2/dex2.json','utf8'));
const TIER=fs.readFileSync('tier_new.txt','utf8').trim().split('\n').map(l=>{const p=l.split('|');return{rank:+p[0],slug:p[1],ko:p[2]}});
const MV=JSON.parse(fs.readFileSync('mv100.json','utf8'));
const P=JSON.parse(fs.readFileSync('power100.json','utf8'));
const MG=JSON.parse(fs.readFileSync('mega.json','utf8'));
const MS=JSON.parse(fs.readFileSync('megastats.json','utf8'));

// ── 누락 기술 보강
Object.assign(MV,{"전기자석파":"전기|변화","버티기":"노말|변화","히트스탬프":"불꽃|물리","열사의대지":"땅|특수"});
Object.assign(P,{"철제광선":140,"일렉트로빔":130,"킬러스핀":30,"애크러뱃":55,"암해머":100,
  "아쿠아커터":70,"얼음숨결":60,"열사의대지":70,"히트스탬프":100,
  // 가변/일격필살/반동형 — 데미지 계산에서 제외(0)
  "열불내기":0,"땅가르기":0,"안다리걸기":0,"카운터":0,"가위자르기":0,"죽기살기":0,"목숨걸기":0,
  "미러코트":0,"분노의앞니":0,"뿔드릴":0,"절대영도":0});
// ── 신규 메가 3종
const NEWMG=[["몰드류","메가몰드류",["땅","강철"],"관통","몰드류나이트",[110,165,100,65,65,103]],
 ["엘레이드","메가엘레이드",["에스퍼","격투"],"예리함","엘레이드나이트",[68,165,95,65,115,110]],
 ["화염레오","메가화염레오",["불꽃","노말"],"불꽃의갈기","화염레오나이트",[86,88,92,129,86,126]]];
for(const [ko,nm,ty,ab,stone,st] of NEWMG){
  const b=DX[ko].stat.reduce((a,c)=>a+c,0), m=st.reduce((a,c)=>a+c,0);
  if(m-b!==100) throw new Error(ko+' 합계 불일치 '+b+'→'+m);
  MG[ko]=[nm,ty,ab,stone]; MS[ko]=st;
}
// 100종 밖 메가 제거
for(const k of Object.keys(MG)) if(!DX[k]){ delete MG[k]; delete MS[k]; }

const mvT=n=>(MV[n]||'노말|변화').split('|')[0], mvC=n=>(MV[n]||'노말|변화').split('|')[1];
const S={}, DATA=[], USE={}, RATE={}, COV={}, ALLMV={};
const baseName=ko=>ko.replace(/\(.*\)/,'').replace(/^(알로라|가라르)\s*/,'').replace(/\s/g,'');
for(const t of TIER){
  const d=DX[t.ko]; if(!d) throw new Error('도감 없음 '+t.ko);
  S[t.ko]=d.stat;
  const moves=Object.keys(d.moves||{});
  ALLMV[t.ko]=moves;
  const atk=moves.filter(m=>mvC(m)!=='변화'&&(P[m]||0)>0);
  DATA.push({rank:t.rank,ko:t.ko,en:t.slug,types:d.types,
    mtypes:[...new Set(atk.map(mvT))].slice(0,3),
    core:atk.slice(0,4), atkMoves:atk, chg:"", s:d.stat, pool:t.rank<=50?'core':'exp',
    abil:Object.keys(d.abil||{}), items:Object.keys(d.item||{}).slice(0,3)});
  // 채용률 (절단 보정)
  const shown=Object.values(d.moves||{}).reduce((a,b)=>a+b,0);
  const sc=shown>0?Math.min(400/shown,1.6):1;
  const floor=moves.length?Math.min(Math.min(...Object.values(d.moves))*0.5,5):25;
  const r={}; for(const m of atk) r[m]=Math.min(100,((d.moves[m]??floor))*sc);
  const all={}; for(const m of moves) all[m]=Math.min(100,d.moves[m]*sc);
  USE[t.ko]={r, all, abil:d.abil||null};
  COV[t.ko]=+(Object.values(r).reduce((a,b)=>a+b,0)/100).toFixed(2);
  // 자기 스톤 채택률 합
  const b=baseName(t.ko);
  const st=Object.entries(d.item||{}).filter(([k])=>/나이트[XYZ]?$/.test(k)&&k.startsWith(b));
  if(st.length) RATE[t.ko]=+st.reduce((s,x)=>s+x[1],0).toFixed(1);
}
fs.writeFileSync('data100.json',JSON.stringify(DATA));
fs.writeFileSync('stats100.json',JSON.stringify(S));
fs.writeFileSync('mv100.json',JSON.stringify(MV));
fs.writeFileSync('power100.json',JSON.stringify(P));
fs.writeFileSync('allmoves100.json',JSON.stringify(ALLMV));
fs.writeFileSync('usage100.json',JSON.stringify(USE));
fs.writeFileSync('stonerate.json',JSON.stringify(RATE));
fs.writeFileSync('cov100.json',JSON.stringify(COV));
fs.writeFileSync('mega.json',JSON.stringify(MG));
fs.writeFileSync('megastats.json',JSON.stringify(MS));
console.log('DATA',DATA.length,'| 메가',Object.keys(MG).length,'| 스톤채택률',Object.keys(RATE).length);
console.log('공격기술 0개인 개체:',DATA.filter(d=>d.atkMoves.length===0).map(d=>d.ko).join(', ')||'없음');
const few=DATA.filter(d=>d.atkMoves.length<2).map(d=>d.ko+'('+d.atkMoves.length+')');
console.log('공격기술 1개 이하:',few.join(', ')||'없음');
console.log('공격기술 보유수 최소:',Object.entries(COV).sort((a,b)=>a[1]-b[1]).slice(0,5).map(x=>x[0]+' '+x[1]).join(', '));
