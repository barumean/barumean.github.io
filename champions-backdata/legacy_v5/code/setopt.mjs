/* 기술 추천기 — 포켓몬 하나를 넣으면 메타 100종(조우확률 가중, 상대 메가 반영)에 대해
   가장 값이 높은 4기를 실채용 상위 10기 안에서 고른다.
   · 공격 스탯은 세트의 주 분류(물리/특수) 하나에만 투자한다 — 반대 분류 기술은 무보정 스탯으로 친다.
   · 쌓기기는 같은 분류 기술에만 배율을 준다(칼춤→물리, 나쁜음모→특수).
   · 선공기: 느린 쪽이 선공기만으로 먼저 넘길 수 있으면 그 선택지를 쓴다(양쪽 모두).
   · 한방기(오버히트·용성군·리프스톰 등): 쓸수록 약해진다. 한 번 쓰고 다른 기술로 넘어가는 경로도 본다.
   · 반동·교체·상태이상 같은 효과는 값을 매기지 못한다 — 그런 변화기는 후보에서 빼고 따로 표시한다. */
import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,ttk,perMove,SETUP,REC,suMul,mvT,mvC,MG,stOf,S_of}=M;
Object.assign(M.CAL,CANON); M.calcNbar();
const NB=M.NBAR.v, C=M.CAL;
const USE=JSON.parse(fs.readFileSync('usage100.json','utf8'));
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const E=JSON.parse(fs.readFileSync('effmega.json','utf8'));
const SR=JSON.parse(fs.readFileSync('stonerate.json','utf8'));
const P=JSON.parse(fs.readFileSync('power100.json','utf8'));
const N=D.length;
export const PRIO=new Set(["전광석화","신속","불릿펀치","마하펀치","얼음뭉치","아쿠아제트","진공파","기습","전광쌍격","물수리검"]);
const DECAY={"오버히트":2,"용성군":2,"리프스톰":2,"사이코부스트":2,"엄청난힘":1};
const RECHARGE=new Set(["기가임팩트","파괴광선"]);
/* 모으기 기술 — 한 턴 모았다가 친다. 가뭄(해)에서는 솔라빔·솔라블레이드가 바로 나간다. */
const CHARGE=new Set(["일렉트로빔","메테오빔","솔라빔","솔라블레이드","로켓박치기","스카이어택","공중날기","다이빙","구멍파기","고스트다이브"]);
const SUNOK=new Set(["솔라빔","솔라블레이드"]);
/* 기술 추천에서는 반동을 켠다 — 반동기와 다른 기술을 비교할 때 반동이 곧 비용이다.
   (팀 모델은 1:1 끝장 싸움에서 반동이 과하게 쌓여 꺼 두었다: config.recoilK) */
const RCL={"이판사판태클":1/3,"플레어드라이브":1/3,"와일드볼트":1/3,"볼트태클":1/3,"우드해머":1/3,"브레이브버드":1/3,
  "돌진":1/4,"저돌맹진":1/4,"파멸의빛":1/2,"양날박치기":1/2,"웨이브태클":1/3,"하이드로스팀":0};
const SUCAT={"칼춤":"물리","용의춤":"물리","벌크업":"물리","배북":"물리","껍질깨기":"*","나쁜음모":"특수","명상":"특수","나비춤":"특수"};
const isAtk=m=>mvC(m)!=='변화' && (P[m]||0)>0;
const SPDSU={"용의춤":1.5,"나비춤":1.5,"껍질깨기":2,"고속이동":2};
const BPSU={"철벽":2,"코튼가드":3};   // 방어 랭크업 → 바디프레스 위력만 오른다
const isSU=m=>(m in SETUP)||(m in SPDSU);
const isREC=m=>m in REC && mvC(m)==='변화';
export const PIVOT=new Set(["유턴","볼트체인지","퀵턴"]);
/* 피해보다 부가효과로 쓰는 공격기 — 피해는 계산하지만 채용 이유(효과)는 값을 못 매긴다 */
export const UTIL=new Set(["속이기","드래곤테일","고속스핀","암석봉인","볼부비부비","탁쳐서떨구기","얼어붙은바람","머드샷","니트로차지"]);
export const role=m=>PRIO.has(m)?"선공":PIVOT.has(m)?"교체":UTIL.has(m)?"효과":(DECAY[m]||RECHARGE.has(m))?"한방":isSU(m)?"쌓기":isREC(m)?"회복":isAtk(m)?"":"모델 밖";
export const unvalued=m=>{const r=role(m);return r==="모델 밖"||r==="교체"||r==="효과";};

const tAdj=(t,f,ty)=>{ if(f.balloon&&ty==='땅')t+=1; if(f.sash&&t<2)t=2; if(f.sturdy&&t<2)t=2; return Math.min(99,t+f.scale*0.5); };
export const CTX={sun:false};
function seqT(HP,dd,mv,alt){
  if(OPT.nuke && CHARGE.has(mv) && !(CTX.sun&&SUNOK.has(mv))){ const h=Math.ceil(HP/dd); const b=2*h; return alt>0? Math.min(b, 2+Math.ceil(Math.max(0,HP-dd)/alt)) : b; }            // 한 기술을 계속 쓰거나(약해지면서), 한 번 쓰고 alt로 넘어가는 최단 턴
  if(dd<=0) return 99;
  let best;
  if(!OPT.nuke) return Math.ceil(HP/dd);
  if(DECAY[mv]){ let h=0,t=0,s=DECAY[mv]; while(h<HP&&t<99){ h+=dd*2/(2+s*t); t++; } best=t; }
  else if(RECHARGE.has(mv)){ const hits=Math.ceil(HP/dd); best=2*hits-1; }
  else return Math.ceil(HP/dd);
  if(alt>0){ const rest=HP-dd; const t2= rest<=0?1 : (RECHARGE.has(mv)?2:1)+Math.ceil(rest/alt); best=Math.min(best,t2); }
  return best;
}
function niOf(pm,moves,mul,suCat,full){   // 세트 기술로 넘기는 턴(max 화력 가정 = 가장 빠른 경로)
  let best=99, bmv=null, bdd=0, alt=0;
  const dmap={};
  for(const x of pm.list){ if(!moves.has(x.mv)) continue;
    const m=(mul>1&&(suCat==="*"||suCat===x.cat||(suCat==="BP"&&x.mv==="바디프레스")))?mul:1;
    dmap[x.mv]={dd:x.dd*m,ty:x.ty}; if(!DECAY[x.mv]&&!RECHARGE.has(x.mv)&&!(CHARGE.has(x.mv)&&!(CTX.sun&&SUNOK.has(x.mv)))) alt=Math.max(alt,x.dd*m); }
  for(const [mv,o] of Object.entries(dmap)){ const t=tAdj(seqT(pm.HP,o.dd,mv,alt),pm,o.ty);
    if(t<best||(t===best&&(RCL[mv]||0)<(RCL[bmv]||0))){best=t;bmv=mv;bdd=o.dd;} }
  return full?{t:best,mv:bmv,dd:bdd}:best;
}
/* 선공기: 큰 기술로 깎다가 마지막 한 방을 선공기로 먼저 넣는 경로.
   (n-1)×(세트 최대 피해) + 선공기 피해 ≥ HP 인 최소 n. 선공기만으로 넘기는 경우도 포함된다. */
function prioT(pm,moves,mul,suCat){
  const f=x=>(mul>1&&(suCat==="*"||suCat===x.cat||(suCat==="BP"&&x.mv==="바디프레스")))?mul:1;
  let dmax=0; for(const x of pm.list) if(moves.has(x.mv)) dmax=Math.max(dmax,x.dd*f(x));
  let b=99;
  for(const x of pm.list){ if(!moves.has(x.mv)||!PRIO.has(x.mv)) continue;
    const dp=x.dd*f(x); if(dp<=0) continue;
    const n = dp>=pm.HP ? 1 : (dmax>0 ? 1+Math.ceil((pm.HP-dp)/dmax) : 99);
    b=Math.min(b,tAdj(n,pm,x.ty)); }
  return b; }
export const OPT={prio:1,nuke:1,floor:15,anchor:70,recoil:1,freeSetup:0};
const clamp=x=>Math.max(-1,Math.min(1,x));

/* 한 개체의 모든 조합을 평가하기 위한 표를 만든다 */
export function prep(i,invs=["물리","특수"]){
  const A=D[i], ko=A.ko;
  const all=(USE[ko]&&USE[ko].all)||{};
  const pool=Object.entries(all).sort((a,b)=>b[1]-a[1]).map(([m,p])=>({mv:m,p:+p.toFixed(1),atk:isAtk(m),su:isSU(m),rec:isREC(m)}));
  const cand=pool.filter(x=>(x.atk||x.su||x.rec) && x.p>=OPT.floor);
  const fixed=cand.filter(x=>x.p>=OPT.anchor).map(x=>x.mv);
  const mi = (MG[ko] && (SR[ko]||0)>=50) ? 1 : 0;
  CTX.sun = (mi&&A.mg&&A.mg.ab==="가뭄") || ((A.ab||{})["가뭄"]||0)>0.5;
  const recQs=[0,...new Set(cand.filter(x=>x.rec).map(x=>REC[x.mv]))];
  const save={atk:A.atkMoves,rec:A.rec,sleep:A.sleep,su:A.su,evSet:A.evSet,recV:A.recV};
  A.atkMoves=[...new Set(cand.filter(x=>x.atk).map(x=>x.mv))];
  const T={}, NJ={};
  for(const inv of invs){ A.evSet=inv==="all"?null:{0:1,1:inv==="물리"?1:0,2:1,3:inv==="특수"?1:0,4:1,5:1};
    for(const q of recQs){ A.rec=q; A.sleep=0;
      for(let j=0;j<N;j++){ if(j===i) continue; const B=D[j];
        const vb=(()=>{const v=B.recV||{p:0,rec:0,sleep:0};const o=[];if(v.p>1e-6)o.push({p:v.p,rec:v.rec,sl:v.sleep});if(1-v.p>1e-6)o.push({p:1-v.p,rec:0,sl:0});return o.length?o:[{p:1,rec:0,sl:0}]})();
        const rb=B.rec, sb=B.sleep;
        for(const mj of (E[j]>0&&MG[B.ko])?[0,1]:[0]){
          vb.forEach((y,yi)=>{ B.rec=y.rec; B.sleep=y.sl;
            (T[inv+q+mj+yi+"/"+j]=perMove(i,j,mi,mj,0,0,1));
            if(inv===invs[0]){          // 상대 쪽 턴수는 내 공격 투자와 무관 → 한 번만
              const nj0=ttk(j,i,mj,mi,0,0);
              const alt=B.su? C.suMax+ttk(j,i,mj,mi,0,0,B.su.mul):null;
              const pmj=perMove(j,i,mj,mi,0,0,1);
              const djmax=pmj.list.reduce((a,x)=>Math.max(a,x.dd),0);
              const jp=new Set(B.atkMoves.filter(m=>PRIO.has(m)));
              NJ[q+"|"+mj+yi+"/"+j]={nj0,alt,djmax,hpI:pmj.HP,fl:{balloon:false,sash:pmj.sash,sturdy:pmj.sturdy,scale:pmj.scale},mulJ:B.su?B.su.mul:1,suP:B.su?B.su.p:0,sl:y.sl,py:y.p,tpj:jp.size?prioT(pmj,new Set(B.atkMoves),1,null):99,
                sj:stOf(B,S_of(j,mj),5)};
            }
          });
        }
        B.rec=rb; B.sleep=sb;
      }
    }
  }
  const si=stOf(A,S_of(i,mi),5);
  Object.assign(A,save);
  return {i,ko,mi,pool,cand,fixed,T,NJ,si,recQs};
}

/* 세트 하나의 메타 점수 (조우확률 가중 평균 value, 상대 메가는 EFF만큼) */
export function score(ctx,set,inv,detail){
  const {i,T,NJ,si}=ctx;
  const moves=new Set(set.filter(isAtk));
  let su=null;
  if(set.includes("바디프레스")) for(const m of set) if(BPSU[m]){ const c={mul:BPSU[m]===3?2.5:2,sp:1,cat:"BP"}; if(!su||c.mul>su.mul) su=c; }
  for(const m of set) if(isSU(m)){
    const mul=(m in SETUP)?suMul(SETUP[m]):1, sp=SPDSU[m]||1;
    const cand={mul,sp,cat:SUCAT[m]||"*"};
    if(cand.cat!=="*" && cand.cat!==inv && mul>1) continue;   // 특수형에 칼춤·용의춤, 물리형에 나쁜음모는 쓰지 않는다
    if(!su || mul*sp>su.mul*su.sp) su=cand; }
  let q=0, sleep=0; for(const m of set) if(isREC(m)&&REC[m]>q){ q=REC[m]; sleep=m==="잠자기"?1:0; }
  const iPrio=OPT.prio&&[...moves].some(m=>PRIO.has(m));
  let tot=0, tw=0; const per=detail?[]:null;
  for(let j=0;j<N;j++){ if(j===i) continue;
    const e=(E[j]>0&&MG[D[j].ko])?E[j]:0;
    let sj_=0;
    for(const [mj,wm] of e>0?[[0,1-e],[1,e]]:[[0,1]]){
      let acc=0, pyS=0, bestMv=null;
      for(let yi=0;yi<2;yi++){
        const nj=NJ[q+"|"+mj+yi+"/"+j]; if(!nj) continue;
        const pm=T[inv+q+mj+yi+"/"+j];
        const nf=moves.size?niOf(pm,moves,1,null,true):{t:99,mv:null,dd:0};
        const ni0=nf.t;
        const rI=(OPT.recoil&&nf.mv&&nj.djmax>0)?(RCL[nf.mv]||0)*Math.min(nf.dd,pm.HP):0;   // 메타몽처럼 고유 기술이 없는 상대는 제외   // 내가 쓰는 기술의 반동 → 상대가 나를 넘기는 턴이 줄어든다
        const njOf=(mulJ)=>{ if(!rI) return null; const d=nj.djmax*mulJ+rI; return d>0?tAdj(Math.ceil(nj.hpI/d),nj.fl,""):99; };
        const nj0=rI?njOf(1):nj.nj0, altj=nj.alt===null?null:(rI?C.suMax+njOf(nj.mulJ):nj.alt);
        let njv=nj0;
        if(C.setup && altj!==null && (ni0>=C.suGate || sleep)) njv = nj.suP*Math.min(nj0,altj)+(1-nj.suP)*nj0;
        const rawnj=njv; if(njv>C.cap)njv=C.cap;
        const jPrio=OPT.prio&&nj.tpj<99;
        const path=(niX,siX,tpX)=>{
          let ni=Math.min(niX,C.cap);
          const fast=siX>nj.sj?C.spd:siX<nj.sj?-C.spd:0;
          let o=clamp(((njv-ni)+fast)/C.K);
          if(iPrio && !jPrio && siX<=nj.sj && tpX<=njv) o=Math.max(o,clamp(((njv-tpX)+C.spd)/C.K));
          if(jPrio && !iPrio && nj.sj<=siX && nj.tpj<=ni) o=Math.min(o,clamp(((nj.tpj-ni)-C.spd)/C.K));
          let d=clamp((rawnj-NB)/NB); if(d>0){ d*=Math.max(0,Math.min(1,1-(ni-NB)/NB)); }
          return (1-C.beta)*o + C.beta*d;
        };
        const tp=iPrio?prioT(pm,moves,1,null):99;
        let val=path(ni0,si,tp);
        if(C.setup && su && (OPT.freeSetup || nj0>=C.suGate || nj.sl)){
          const niB=C.suMax+niOf(pm,moves,su.mul,su.cat);
          val=Math.max(val, path(niB, si*su.sp, iPrio?C.suMax+prioT(pm,moves,su.mul,su.cat):99));
        }
        acc += nj.py*val; pyS+=nj.py;
        if(detail&&yi===0&&mj===0&&moves.size){ let bt=99; for(const x of pm.list){ if(!moves.has(x.mv))continue; const t=tAdj(seqT(pm.HP,x.dd,x.mv,0),pm,x.ty); if(t<bt){bt=t;bestMv=x.mv;} } }
      }
      sj_+=wm*(acc/(pyS||1));
      if(detail&&mj===0) per.push({j,v:0,mv:bestMv});
    }
    if(detail) per[per.length-1].v=sj_;
    tot+=W[j]*sj_; tw+=W[j];
  }
  return detail? {s:tot/tw, per} : tot/tw;
}
function* combos(arr,k,start=0,cur=[]){ if(cur.length===k){ yield cur.slice(); return; }
  for(let x=start;x<=arr.length-(k-cur.length);x++){ cur.push(arr[x]); yield* combos(arr,k,x+1,cur); cur.pop(); } }
export function bestSets(ctx,k){
  const fx=ctx.fixed.slice(0,k), rest=ctx.cand.map(x=>x.mv).filter(m=>!fx.includes(m));
  const kk=Math.min(k-fx.length,rest.length); const out=[];
  for(const r of combos(rest,kk)) for(const inv of ["물리","특수"]){ const s=[...fx,...r];
    if(!s.some(isAtk)) continue;
    out.push({set:s,inv,s:score(ctx,s,inv)});
  }
  out.sort((a,b)=>b.s-a.s);
  return out;
}
