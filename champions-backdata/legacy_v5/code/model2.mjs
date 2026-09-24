import fs from 'fs';
const D=JSON.parse(fs.readFileSync('data100.json','utf8'));
const S=JSON.parse(fs.readFileSync('stats100.json','utf8'));
const MS=JSON.parse(fs.readFileSync('megastats.json','utf8'));
const P=JSON.parse(fs.readFileSync('power100.json','utf8'));
const CH=JSON.parse(fs.readFileSync('chart.json','utf8'));
const MG=JSON.parse(fs.readFileSync('mega.json','utf8'));
const MV=JSON.parse(fs.readFileSync('mv100.json','utf8'));
const ALLMV=JSON.parse(fs.readFileSync('allmoves100.json','utf8'));
const USE=JSON.parse(fs.readFileSync('usage100.json','utf8'));

// ── 튜닝 파라미터
export const CAL={ setVar:1, sleepGate:0.5, multiHit:1, bodyPress:1, recoilK:1, mgAb:1, evMode:'all252', slotsAll:1, setup:1, suGate:3, suMax:1, recHP:1.4, recOFF:0.7, dittoPen:1, spd:1.0, K:3.0, useUsage:1, noSuicide:1, useAbil:1, beta:0, slots:0, mix:1, cap:99, dgate:0, abIm:1, abHalf:1, abCond:1, abIntim:1, abStab:1 };
export const NBAR={v:null};

// 회복기의 '질' — 신뢰회복 1.0, 잠자기는 2턴 경직이라 0.4, 뿌리박기는 교체 불가라 0.4
const REC={"HP회복":1,"자기재생":1,"광합성":1,"아침햇살":1,"달빛":1,"날개쉬기":1,"게으름피우기":1,
 "회복지령":1,"희망사항":1,"밀크마시기":1,"알깨기":1,"조가비닫기":1,"모래모으기":1,
 "잠자기":.4,"뿌리박기":.4,"드레인펀치":.35,"기가드레인":.35,"흡혈":.35,"힘흡수":.5,"드레인키스":.35};
const SUICIDE=new Set(["자폭","대폭발","미스트버스트","죽기살기","목숨걸기"]);
/* 반동기 — 준 피해의 일부를 스스로 받는다. 상대를 몇 턴에 넘기느냐에 직접 들어간다. */
const RECOIL={"이판사판태클":1/3,"플레어드라이브":1/3,"와일드볼트":1/3,"볼트태클":1/3,
  "우드해머":1/3,"브레이브버드":1/3,"돌진":1/4,"저돌맹진":1/4,"공중날기":0,"물리쳐":0};
/* 공격 랭크업 기술 → 랭크 수. 상대가 2턴 안에 압박받지 않으면 한 턴을 여기에 쓴다(= 기점). */
const SETUP={"칼춤":2,"나쁜음모":2,"껍질깨기":2,"배북":6,"용의춤":1,"명상":1,"벌크업":1,
  "나비춤":1,"성장":1,"똬리틀기":1,"저주":1};
const suMul=st=>st>=6?4:st>=2?2:1.5;
// ── 아이템: 1:1 모델에 반영되는 효과만 계수로 정의한다
// mo=자기 기술 위력 배율, mh=실효 HP 배율, ms=스피드 배율, sash=1타 생존,
// regen=매턴 회복(최대HP 비율), seOnly=효과굉장일 때만 위력배율, stabBoost=주력 자속 타입만 위력배율,
// helmet=상대 접촉기에 상대 최대HP 비율만큼 반동, balloon=땅 기술 1회 무효
export const ITEM=[
 {k:"none",  n:"없음"},
 {k:"orb",   n:"생명의구슬",   mo:1.30, mh:0.88},
 {k:"scarf", n:"구애스카프",   ms:1.5},
 {k:"sash",  n:"기합의띠",     sash:1},
 {k:"sitrus",n:"자뭉열매",     mh:1.25},
 {k:"left",  n:"먹다남은음식", regen:1/16},
 {k:"belt",  n:"달인의띠",     seOnly:1.2},
 {k:"plate", n:"타입강화",     stabBoost:1.2},
 {k:"helm",  n:"울퉁불퉁멧",   helmet:1/6},
 {k:"ball",  n:"풍선",         balloon:1}
];
const IT=c=>ITEM[c]||ITEM[0];
const mvT=n=>(MV[n]||'노말|변화').split('|')[0], mvC=n=>(MV[n]||'노말|변화').split('|')[1];
const eff=(a,d)=>{const r=CH[a];return r&&d in r?r[d]:1};
const vs=(a,ts)=>ts.reduce((m,d)=>m*eff(a,d),1);
/* 노력치 가정. 'all252'는 모든 능력치에 252를 동시에 준 현재 가정(실전 불가능, 리뷰 P0),
   'offense'/'bulk'는 508 예산을 지키는 2스탯 투자 가정으로 민감도 확인용. */
const st=b=>b+52, hpOf=b=>b+107;
const stN=b=>b+20, hpN=b=>b+75;                 // 0노력치·31개체값·레벨50
const inv=(m,k)=>{                               // k: 0=HP 1=A 2=B 3=C 4=D 5=S
  const msk = m.evSet || (CAL.evMode==='offense'?m.evOff:CAL.evMode==='bulk'?m.evBulk:null);
  return msk? !!msk[k] : true;
};
const pickMask=m=>CAL.evMode==='offense'?m.evOff:CAL.evMode==='bulk'?m.evBulk:null;
const stOf=(m,S,k)=>k===0?(inv(m,0)?hpOf(S[0]):hpN(S[0])):(inv(m,k)?st(S[k]):stN(S[k]));

// ── 특성: 채용률로 가중한 피해 배율
const IMMUNE={"부유":"땅","저수":"물","축전":"전기","피뢰침":"전기","타오르는불꽃":"불꽃","초식":"풀",
  "흙먹기":"땅","마중물":"물","전기엔진":"전기","건조피부":"물","증기기관":null,"방진":null};
const HALF={"두꺼운지방":["불꽃","얼음"],"헤비메탈":[],"수포불":["불꽃"]};
/* 조건부 경감 — 발동 조건을 분리해 처리한다(리뷰 P1 반영).
   FILTER: 효과가 굉장할 때만 ×0.75.  SCALE(멀티스케일): 만피 1발만 절반 → 턴수에 +0.5×채용률.
   이상한비늘: 상태이상일 때만 발동하는데 이 모델에는 상태이상이 없으므로 중립(1.0)으로 둔다. */
const FILTER=new Set(["프리즘아머","필터","하드로크"]);
const SCALE=new Set(["멀티스케일"]);
const COND={};
const STAB2=new Set(["적응력"]);
const ALLSTAB=new Set(["변환자재","리베로"]);
const INTIM=new Set(["위협"]);
const STURDY=new Set(["옹골참"]);
const TECH=new Set(["테크니션"]);
/* 연속기 — power 표에는 1타 위력만 들어 있다. 명중 실패는 다른 기술처럼 무시하고 타수만 곱한다.
   2~5회 기술은 평균 3.1타(35/35/15/15%), 스킬링크면 5타. */
const HIT25={"고드름침":1,"록블라스트":1,"스케일샷":1,"물수리검":1,"바늘미사일":1,"씨기관총":1,"연속뺨치기":1,"본러시":1};
const HITFIX={"트리플악셀":6,"트리플킥":6,"더블윙":2,"드래곤애로":2,"더블어택":2,"기어소서":2,"트윈빔":2,"더블펀처":2};
const SKILL=new Set(["스킬링크"]);
/* -스킨 특성: 노말 기술을 해당 타입으로 바꾸고 위력 ×1.2 (자속도 새 타입 기준) */
const SKIN={"스카이스킨":"비행","페어리스킨":"페어리","프리즈스킨":"얼음","일렉트릭스킨":"전기","노말스킨":"노말"};

D.forEach(m=>{ m.s=S[m.ko];
  const mv=ALLMV[m.ko]||[];
  // 회복기는 '질 × 실제 채용률'로만 값을 준다 — 아무도 안 넣는 회복기는 없는 것과 같다
  const uall=(USE[m.ko]&&USE[m.ko].all)||{};
  /* 회복기는 실제로 4칸 안에 들 때만 값을 준다(리뷰 반영).
     채용률이 있어도 5번째 이하면 그 세트는 회복기를 못 넣은 것이므로 회복으로 치지 않는다. */
  /* 세트 변형 — 회복기를 '실제로 든 세트'와 '안 든 세트'를 확률로 나눈다(리뷰 반영).
     회복·잠자기 페널티를 같은 세트 정의 위에서 계산하기 위한 최소 클러스터링이다.
     A: 그 회복기를 든 세트(확률 = 채용률) → 회복 있음, 잠자기면 기점 허용
     B: 안 든 세트(1-확률)               → 회복 없음, 기점 허용 없음 */
  let bestR=null;
  for(const x of mv){ const q=REC[x]||0; if(!q) continue;
    const pr=Math.min(1,(uall[x]??0)/100); if(pr<=0) continue;
    const sc=q*pr; if(!bestR||sc>bestR.sc) bestR={mv:x,q,p:pr,sc}; }
  m.recV = bestR? {p:bestR.p, rec:bestR.q, sleep:bestR.mv==="잠자기"?1:0} : {p:0,rec:0,sleep:0};
  m.rec  = bestR? bestR.sc : 0;      // 기대값 — 진단·MVT 텐서용
  m.sleep= m.recV.sleep*m.recV.p;
  m.mg=MG[m.ko]?{types:MG[m.ko][1],ab:MG[m.ko][2],s:MS[m.ko]||S[m.ko]}:null;
  const A=(USE[m.ko]&&USE[m.ko].abil)||{};
  const tot=Object.values(A).reduce((a,b)=>a+b,0)||100;
  m.ab={};                       // 특성명 -> 확률
  for(const[k,v] of Object.entries(A)) m.ab[k]=v/tot;
  /* 재생력은 '교체해야' 발동한다. 이 모델에는 교체가 없으므로 회복으로 치지 않는다(리뷰 P1 반영). */
  // 받는 피해 배율(타입별)
  const sumOf=(ab,S)=>Object.entries(ab).filter(([k])=>S.has(k)).reduce((a,[,p])=>a+p,0);
  const derive=ab=>({
    intim:sumOf(ab,INTIM), sturdy:sumOf(ab,STURDY), filt:sumOf(ab,FILTER), scale:sumOf(ab,SCALE),
    stab2:sumOf(ab,STAB2), allstab:sumOf(ab,ALLSTAB), tech:sumOf(ab,TECH), skill:sumOf(ab,SKILL),
    skin:Object.entries(ab).map(([k,p])=>SKIN[k]?[SKIN[k],p]:null).filter(Boolean)[0]||null,
    dm:t=>{ let x=0;
      for(const[k,p] of Object.entries(ab)){
        let f=1;
        if(CAL.abIm&&IMMUNE[k]===t)f=0;
        else if(CAL.abHalf&&HALF[k]&&HALF[k].includes(t))f=0.5;
        x+=p*f; }
      return (CAL.abIm||CAL.abHalf||CAL.abCond)? x+(1-Object.values(ab).reduce((a,b)=>a+b,0)) : 1; }
  });
  Object.assign(m,derive(m.ab));
  /* 메가는 자기 특성을 쓴다 — 기본형 특성(위협 등)을 그대로 물려주던 것을 바로잡는다 */
  m.MA = m.mg ? derive({[m.mg.ab]:1}) : null;
  m.recoil = m.atkMoves.some(x=>RECOIL[x]>0);
  // 타입강화 아이템이 실제로 올려주는 타입 = 채용률이 가장 높은 자속 공격기의 타입
  const rr=(USE[m.ko]&&USE[m.ko].r)||{};
  const sb=Object.entries(rr).filter(([n])=>m.types.includes(mvT(n))&&mvC(n)!=='변화').sort((a,b)=>b[1]-a[1])[0];
  m.bty=sb?mvT(sb[0]):m.types[0];
  /* 508 예산 가정용 투자 마스크. 채용 공격기의 물리/특수 비중으로 주 공격 스탯을 정한다. */
  let ph=0,sp=0;
  for(const [n,v] of Object.entries(rr)){ const c=mvC(n); if(c==='물리')ph+=v; else if(c==='특수')sp+=v; }
  const atkK = ph>=sp?1:3, defK = ph>=sp?4:2;      // 공격 반대쪽 방어에 투자(대략적 가정)
  m.evOff={0:0,1:0,2:0,3:0,4:0,5:0}; m.evOff[atkK]=1; m.evOff[5]=1;
  m.evBulk={0:1,1:0,2:0,3:0,4:0,5:0}; m.evBulk[defK]=1;
  // 쌓기 보유: 채용률 10% 이상인 공격 랭크업 기술 중 가장 많이 쓰이는 것
  m.su=null;
  for(const [mv,st] of Object.entries(SETUP)){
    if(mv==="저주" && m.types.includes("고스트")) continue;   // 고스트 저주는 HP 소모형
    const p=(uall[mv]??0)/100; if(p<0.10) continue;
    if(!m.su || p>m.su.p) m.su={mv,p,mul:suMul(st)};
  }
});
const BLADE={"킬가르도":[60,140,50,140,50,60]};
const T_of=(i,mg)=>(mg&&D[i].mg)?D[i].mg.types:D[i].types;
const S_of=(i,mg)=>(mg&&D[i].mg)?D[i].mg.s:D[i].s;
const A_of=(i,mg)=>BLADE[D[i].ko]||S_of(i,mg);
/* 특성 참조: 메가 상태면 메가 고유 특성을 쓴다 */
const AB=(m,mg)=>(mg&&m.MA&&CAL.mgAb)?m.MA:m;

// ── 기술별 피해 + 채용률 목록 (내림차순)
function moveList(i,j,mi,mj,ii,bo){
  const IA=IT(ii);
  const A=D[i],B=D[j],AS=A_of(i,mi),BS=S_of(j,mj),bt=T_of(j,mj),at=T_of(i,mi);
  const Aa=AB(A,mi), Ba=AB(B,mj);
  const use=(USE[A.ko]&&USE[A.ko].r)||{};
  const out=[];
  for(const mv of A.atkMoves){
    if(mvC(mv)==='변화')continue;
    if(CAL.noSuicide&&SUICIDE.has(mv))continue;
    let pw=P[mv]||0; if(!pw)continue;
    let ty=mvT(mv);
    /* -스킨: 노말 기술을 특성 타입으로 바꾸고 위력 ×1.2 */
    if(Aa.skin && ty==='노말' && Aa.skin[0]!=='노말'){ ty=Aa.skin[0]; pw*=1+0.2*Aa.skin[1]; }
    if(Aa.tech>0&&pw<=60) pw*= (1+Aa.tech*0.5);
    if(CAL.multiHit){ if(HIT25[mv]) pw*=3.1+1.9*(Aa.skill||0); else if(HITFIX[mv]) pw*=HITFIX[mv]; }
    const cat=mvC(mv);
    let atk=(mv==='바디프레스'&&CAL.bodyPress)?stOf(A,AS,2):stOf(A,AS,cat==='물리'?1:3);   // 바디프레스는 자기 방어로 친다
    if(CAL.abIntim&&cat==='물리'&&Ba.intim>0) atk*= (1-Ba.intim/3);            // 위협 = 공격 1랭크 down
    const def=stOf(B,BS,cat==='물리'?2:4);
    let stab=at.includes(ty)?1.5:1;
    if(CAL.abStab){ if(Aa.stab2>0&&at.includes(ty)) stab=1.5+Aa.stab2*0.5;
      if(Aa.allstab>0&&!at.includes(ty)) stab=1+Aa.allstab*0.5; }
    let e=vs(ty,bt)*Ba.dm(ty);
    if(CAL.abCond && Ba.filt>0 && vs(ty,bt)>1) e*= (1-Ba.filt*0.25);   // 필터·하드로크·프리즘아머
    let d=(Math.floor(Math.floor(22*pw*atk/def)/50)+2)*stab*e;
    if(d<=0) continue;            // 무효/면역이면 그 기술은 애초에 선택지가 아니다
    if(IA.mo) d*=IA.mo;
    if(IA.seOnly && e>1) d*=IA.seOnly;
    if(IA.stabBoost && ty===A.bty) d*=IA.stabBoost;
    if(bo) d*=bo;                      // 랭크업 배율
    const p=Math.min(1,(use[mv]??50)/100);
    out.push({mv,d,p,ty,cat});
  }
  if(CAL.slots){
    /* 4칸 제약. slotsAll=1이면 변화기까지 포함한 전체 채용률에서 상위 N칸을 뽑고
       그 안의 공격기만 남긴다 — 용의춤·날개쉬기가 칸을 먹는 실제 세트를 반영한다.
       slotsAll=0이면 공격기 중에서만 상위 N칸(느슨한 제약). */
    const src = CAL.slotsAll ? ((USE[A.ko]&&USE[A.ko].all)||use) : use;
    const keep=new Set(Object.entries(src).sort((a,b)=>b[1]-a[1]).slice(0,CAL.slots).map(x=>x[0]));
    const f=out.filter(o=>keep.has(o.mv));
    if(f.length){ f.forEach(o=>o.p=1); f.sort((a,b)=>b.d-a.d); return f; }
    return [];                        // 4칸 안에 때릴 기술이 하나도 없으면 실제로 못 때린다
  }
  out.sort((a,b)=>b.d-a.d);
  return out;
}
const DITTO="메타몽";
// ── 기대 TTK: 채용률로 "가장 좋은 기술을 실제로 들고 있을 확률"을 가중
function ttkOne(i,j,mi,mj,usage,ii,ij,bo){
  const IA=IT(ii), IB=IT(ij);
  const src = D[i].ko===DITTO ? j : i;              // 메타몽은 상대를 복사
  const L = D[i].ko===DITTO ? moveList(j,j,mj,mj,ii,bo) : moveList(i,j,mi,mj,ii,bo);
  if(!L.length) return 99;
  const maxHP=stOf(D[j],S_of(j,mj),0);
  let HP=maxHP;
  HP *= 1 + (CAL.recHP-1)*D[j].rec;              // 회복 비중만큼 실효 HP 증가
  if(IB.mh) HP*=IB.mh;                           // 자뭉열매 / 생명의구슬 반동
  const regen = IB.regen? maxHP*IB.regen : 0;    // 먹다남은음식 — 매턴 회복분은 피해에서 뺀다
  let helm=0;
  if(IA.helmet || D[j].recoil){
    const LJ=moveList(j,i,mj,mi,0);
    // 울퉁불퉁멧: 상대가 접촉기를 쓰면 매턴 자기 최대HP의 1/6
    if(IA.helmet) helm += maxHP*IA.helmet*((LJ.length&&LJ[0].cat==='물리')?0.85:0.15);
    /* 반동: j가 실제로 고르는 기술의 반동 비율 × 그 기술이 내는 피해를 j가 스스로 받는다 */
    if(CAL.recoilK && D[j].recoil && LJ.length){
      let r=0, rest2=1;
      for(const m of LJ){ const mp=CAL.mix>=1?m.p:1; const q=rest2*mp;
        if(q>1e-6) r += q*(RECOIL[m.mv]||0)*m.d*CAL.recoilK;
        rest2*=(1-mp); if(rest2<1e-6) break; }
      helm += r;
    }
  }
  const off = 1 - (1-CAL.recOFF)*D[src].rec;     // 회복 턴만큼 화력 손실
  let acc=0, rest=1;
  for(const m of L){
    const mp = usage? m.p : 1;
    const q = rest*mp;
    if(q>1e-6){
      const dd=m.d*off + helm - regen;
      let t = dd>0? Math.ceil(HP/dd) : 99;
      if(IB.balloon && m.ty==='땅') t+=1;            // 풍선 — 땅 기술 1회 무효
      if(IB.sash && t<2) t=2;                        // 기합의띠
      if(AB(D[j],mj).sturdy>0.5 && t<2) t=2;               // 옹골참
      if(CAL.abCond && AB(D[j],mj).scale>0) t += AB(D[j],mj).scale*0.5;   // 멀티스케일 — 만피 1발만 절반
      acc += q*Math.min(t,99);
    }
    rest *= (1-mp);
    if(rest<1e-6) break;
  }
  if(rest>0.999) return 99;
  acc/= (1-rest);                                    // "공격기술을 하나도 안 듦" 은 표본 결손 → 정규화
  if(D[i].ko===DITTO) acc+=CAL.dittoPen;
  return Math.min(acc,99);
}
function ttk(i,j,mi,mj,ii,ij,bo){
  if(CAL.mix>=1) return ttkOne(i,j,mi,mj,1,ii,ij,bo);
  if(CAL.mix<=0) return ttkOne(i,j,mi,mj,0,ii,ij,bo);
  return (1-CAL.mix)*ttkOne(i,j,mi,mj,0,ii,ij,bo)+CAL.mix*ttkOne(i,j,mi,mj,1,ii,ij,bo);
}
export function value(i,j,mi,mj,ii,ij){
  if(i===j)return 0;
  if(!CAL.setVar) return value1(i,j,mi,mj,ii,ij);
  const A=D[i], B=D[j];
  const mk=m=>{const v=m.recV||{p:0,rec:0,sleep:0};
    const out=[]; if(v.p>1e-6) out.push({p:v.p,rec:v.rec,sl:v.sleep});
    if(1-v.p>1e-6) out.push({p:1-v.p,rec:0,sl:0}); return out.length?out:[{p:1,rec:0,sl:0}];};
  const va=mk(A), vb=mk(B);
  const ra=A.rec,sa=A.sleep,rb=B.rec,sb=B.sleep;
  let acc=0;
  for(const x of va) for(const y of vb){
    A.rec=x.rec; A.sleep=x.sl; B.rec=y.rec; B.sleep=y.sl;
    acc += x.p*y.p*value1(i,j,mi,mj,ii,ij);
  }
  A.rec=ra;A.sleep=sa;B.rec=rb;B.sleep=sb;
  return acc;
}
function value1(i,j,mi,mj,ii,ij){
  let ni=ttk(i,j,mi,mj,ii,ij), nj=ttk(j,i,mj,mi,ij,ii);
  if(CAL.setup){
    /* 2턴 안에 넘기지 못하면 상대는 그 턴을 랭크업에 쓸 수 있다.
       채용률만큼만 가중하고, 쌓는 게 손해면(1턴 + 강화 후 턴수 ≥ 그냥 때리기) 쌓지 않는다. */
    const ni0=ni, nj0=nj, A=D[i], Bm=D[j];
    /* 내가 잠자기를 쓰는 세트면 2턴을 그냥 내주므로, 턴수와 무관하게 상대에게 쌓기 창이 열린다 */
    const iSleeps = CAL.sleepGate>0 && A.sleep>=CAL.sleepGate;
    if(Bm.su && (ni0>=CAL.suGate || iSleeps)){
      const alt=CAL.suMax+ttk(j,i,mj,mi,ij,ii,Bm.su.mul);
      nj = Bm.su.p*Math.min(nj0,alt) + (1-Bm.su.p)*nj0;
    }
    const jSleeps = CAL.sleepGate>0 && Bm.sleep>=CAL.sleepGate;
    if(A.su && (nj0>=CAL.suGate || jSleeps)){
      const alt=CAL.suMax+ttk(i,j,mi,mj,ii,ij,A.su.mul);
      ni = A.su.p*Math.min(ni0,alt) + (1-A.su.p)*ni0;
    }
  }
  // 실전에서는 n턴 넘게 못 잡으면 그냥 교체한다 → 턴수 상한
  const cp=CAL.cap; const rawnj=nj;
  if(ni>cp)ni=cp; if(nj>cp)nj=cp;
  const si=stOf(D[i],S_of(i,mi),5)*(IT(ii).ms||1), sj=stOf(D[j],S_of(j,mj),5)*(IT(ij).ms||1);
  const fast=si>sj?CAL.spd:si<sj?-CAL.spd:0;
  const o=Math.max(-1,Math.min(1,((nj-ni)+fast)/CAL.K));
  if(!CAL.beta) return o;
  const nb=NBAR.v||4;
  let d=Math.max(-1,Math.min(1,(rawnj-nb)/nb));        // 평균보다 얼마나 오래 버티나
  // dgate: 내구는 '역으로 찌를 수 있을 때'만 값이다 — 버티기만 하는 건 교체당하면 끝
  if(CAL.dgate===1 && d>0 && ni>nj) d=0;               // 지는 싸움의 내구는 0
  if(CAL.dgate===2 && d>0){                            // 위협도로 비례 감쇠
    const thr=Math.max(0,Math.min(1,1-(ni-nb)/nb));
    d*=thr;
  }
  return (1-CAL.beta)*o + CAL.beta*d;
}
/* 기술 1개만으로 j를 넘기는 데 걸리는 턴. 내 지닌물건은 없음, 상대는 ij를 든 것으로 본다. */
export function movesTTK(i,j,ij,bo){
  const IB=IT(ij), out={};
  const L=moveList(i,j,0,0,0,bo);
  if(!L.length) return out;
  const maxHP=hpOf(S_of(j,0)[0]);
  let HP=maxHP*(1+(CAL.recHP-1)*D[j].rec);
  if(IB.mh) HP*=IB.mh;
  const regen=IB.regen? maxHP*IB.regen:0;
  const off=1-(1-CAL.recOFF)*D[i].rec;
  for(const m of L){
    const dd=m.d*off-regen;
    let t = dd>0? Math.ceil(HP/dd) : 99;
    if(IB.balloon && m.ty==='땅') t+=1;
    if(IB.sash && t<2) t=2;
    if(D[j].sturdy>0.5 && t<2) t=2;
    out[m.mv]=Math.min(t,99);
  }
  return out;
}
/* 기술 추천기용 — ttkOne과 같은 계산 경로로, 기술별 1턴 실효 피해와 보정 플래그를 돌려준다.
   (조합 평가는 setopt.mjs가 이걸 조합해서 한다) */
export function perMove(i,j,mi,mj,ii,ij,bo){
  const IA=IT(ii), IB=IT(ij);
  const L=moveList(i,j,mi,mj,ii,bo);
  const maxHP=stOf(D[j],S_of(j,mj),0);
  let HP=maxHP*(1+(CAL.recHP-1)*D[j].rec);
  if(IB.mh) HP*=IB.mh;
  const regen=IB.regen? maxHP*IB.regen:0;
  let helm=0;
  if(IA.helmet){ const LJ=moveList(j,i,mj,mi,0); helm+=maxHP*IA.helmet*((LJ.length&&LJ[0].cat==='물리')?0.85:0.15); }
  const off=1-(1-CAL.recOFF)*D[i].rec;
  const Bj=AB(D[j],mj);
  return {HP, list:L.map(m=>({mv:m.mv,ty:m.ty,cat:m.cat,dd:m.d*off+helm-regen})),
    balloon:!!IB.balloon, sash:!!IB.sash, sturdy:Bj.sturdy>0.5, scale:CAL.abCond?Bj.scale:0};
}
export function calcNbar(){let s=0,c=0;for(let i=0;i<D.length;i++)for(let j=0;j<D.length;j++){if(i===j)continue;s+=ttk(j,i,0,0);c++}NBAR.v=s/c;return NBAR.v}
export {D,ttk,moveList,hpOf,st,S_of,T_of,MG,SETUP,REC,suMul,stOf,mvT,mvC};
