import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,ttk,value,calcNbar,ITEM,MG}=M;
Object.assign(M.CAL, CANON);
calcNbar();
const O=process.env.EXPORT_DIR||'/tmp/bd/';
const IB=JSON.parse(fs.readFileSync('item_blocks.json','utf8'));
const MB=JSON.parse(fs.readFileSync('mv_blocks.json','utf8'));
const SB=JSON.parse(fs.readFileSync('su_blocks.json','utf8'));
const DEC=JSON.parse(fs.readFileSync('blk_dec.js','utf8').match(/const DEC=(\{.*\});/s)[1]);
const COV=JSON.parse(fs.readFileSync('cov100.json','utf8'));
const OPPW=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const OPPS=JSON.parse(fs.readFileSync('opps100.json','utf8'));
const RATE=JSON.parse(fs.readFileSync('stonerate.json','utf8'));
const OPPIT=IB.OPPIT, N=D.length;
const csv=(f,head,rows)=>fs.writeFileSync(O+'csv/'+f,'﻿'+[head.join(','),...rows.map(r=>r.map(x=>{
  const s=String(x??''); return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}).join(','))].join('\n'));

/* 1) 개체 요약 */
csv('01_mons.csv',
 ['rank','ko','en','type1','type2','HP','Atk','Def','SpA','SpD','Spe','BST','abilities',
  'mega','mega_stone','stone_rate_pct','ladder_count_149','opp_weight',
  'model_off','model_dur','model_total','dur_share','recovery_q',
  'atk_move_slots','setup_move','setup_pct','setup_mul','top_item','top_item_pct','item_class'],
 D.map((m,i)=>{
   const d=DEC[m.ko]||[null,null,null,null,null];
   const su=SB.SUMON.find(x=>x[0]===i);
   const it=(IB.IUSE[m.ko]||[])[0]||[];
   return [m.rank,m.ko,m.en,m.types[0],m.types[1]||'',...m.s,m.s.reduce((a,b)=>a+b,0),
     Object.keys(m.ab||{}).join('|'),
     MG[m.ko]?MG[m.ko][0]:'', MG[m.ko]?MG[m.ko][3]||'':'', RATE[m.ko]??'',
     OPPS.flat().filter(x=>x===i).length, OPPW[i].toFixed(5),
     d[0],d[1],d[2],d[3],(m.rec??0).toFixed(3),
     COV[m.ko], su?su[1]:'', su?su[2]:'', su?su[3]:'', it[0]||'', it[1]??'', it[2]??''];
 }));

/* 2) 매치업 롱포맷 9,900행 */
const rows=[];
for(let i=0;i<N;i++)for(let j=0;j<N;j++){ if(i===j)continue;
  rows.push([D[i].ko,D[j].ko,D[i].rank,D[j].rank,
    ttk(i,j,0,0).toFixed(3), ttk(j,i,0,0).toFixed(3),
    value(i,j,0,0).toFixed(4),
    MG[D[i].ko]?value(i,j,1,0).toFixed(4):'',
    value(i,j,0,0,0,OPPIT[j]).toFixed(4),
    MG[D[j].ko]?value(i,j,0,1,0,0).toFixed(4):'',
    OPPIT[j]?ITEM[OPPIT[j]].n:'없음']);
}
csv('02_matchups.csv',
 ['atk_ko','def_ko','atk_rank','def_rank','ttk_atk_to_def','ttk_def_to_atk',
  'v_base','v_atk_mega','v_def_has_item','v_def_mega','def_assumed_item'], rows);

/* 3) 기술 채용률 + 기술별 필요 턴수 */
const mrows=[];
for(const [ko,o] of Object.entries(MB.MVU))
  for(const [mv,p] of Object.entries(o)) mrows.push([ko,mv,p]);
csv('03_move_usage.csv',['ko','move','usage_pct'],mrows);
const trows=[];
for(const [ko,o] of Object.entries(MB.MVT)){
  for(const [mv,s] of Object.entries(o))
    for(let j=0;j<N;j++){ const c=s.charCodeAt(j), t=c>96?c-71:c-65;
      if(D.findIndex(d=>d.ko===ko)===j) continue;
      trows.push([ko,mv,D[j].ko,t===0?'무효':t]); }
}
csv('04_move_ttk.csv',['atk_ko','move','def_ko','turns_to_ko'],trows);

/* 4) 아이템 */
csv('05_item_usage.csv',['ko','item','usage_pct','model_class'],
  Object.entries(IB.IUSE).flatMap(([ko,a])=>a.map(x=>[ko,x[0],x[1],x[2]?ITEM[x[2]].n:'(모델 밖)'])));
csv('06_item_value.csv',['ko','item_class','class_usage_share','model_delta'],
  D.flatMap((m,i)=>ITEM.map((it,c)=>c?[m.ko,it.n,(IB.IUSEC[i][c]*100).toFixed(1),IB.IVAL[i][c]]:null).filter(Boolean)));
csv('07_item_agg.csv',['item','avg_usage_pct_over_100','mons_with_10pct_plus','model_class'],
  IB.AGG.map(([n,a,c,cl])=>[n,a,c,cl?ITEM[cl].n:'(모델 밖)']));

/* 5) 쌓기(기점) */
csv('08_setup_threats.csv',['ko','rank','setup_move','usage_pct','atk_multiplier','opp_weight'],
  SB.SUMON.map(([j,mv,p,mul])=>[D[j].ko,D[j].rank,mv,p,mul,OPPW[j].toFixed(5)]));
const srows=[];
for(const [j,mv,p,mul] of SB.SUMON){
  const s=SB.SUTK[j];
  for(let a=0;a<N;a++){ if(a===j)continue;
    const c=s.charCodeAt(a), t=c>96?c-71:c-65;
    srows.push([D[j].ko,mv,mul,D[a].ko,t]); }
}
csv('09_setup_sweep_turns.csv',['setup_ko','setup_move','atk_mul','target_ko','turns_after_1_setup'],srows);

/* 6) 래더 표본 팀 */
csv('10_ladder_teams.csv',['team_no','size','members'],
  OPPS.map((t,k)=>[k+1,t.length,t.map(x=>D[x].ko).join('|')]));

/* 7) 후보 팀 + 내시 결과 — 상대 메가(EFF) 반영. 메가 슬롯·무답 노출은 아이템 없는 기준값으로 다시 계산 */
const V0=JSON.parse(fs.readFileSync('V100.json','utf8')), VM0=JSON.parse(fs.readFileSync('V100m.json','utf8'));
const VO0=JSON.parse(fs.readFileSync('V100o.json','utf8')), VMM0=JSON.parse(fs.readFileSync('V100mm.json','utf8'));
const EFF=JSON.parse(fs.readFileSync('effmega.json','utf8'));
const idxK={}; D.forEach((d,i)=>idxK[d.ko]=i);
const mv0=(i,j,g)=>{ const b=(i===g?VM0:V0)[i][j]; const e=EFF[j]; if(!(e>0)||!MG[D[j].ko]) return b;
  return (1-e)*b+e*((i===g)?VMM0[i][j]:VO0[i][j]); };
function teamDiag(T){
  const hold=T.filter(i=>MG[D[i].ko]).slice(0,2); let best=null;
  for(const g of [-1,...hold]){ let s=0,gap=0,zero=0,tw=0;
    for(let j=0;j<N;j++){ tw+=OPPW[j]; if(T.includes(j))continue; const a=T.map(i=>mv0(i,j,g)).sort((x,y)=>y-x);
      s+=OPPW[j]*(a[0]+a[1])/2; const n=a.filter(x=>x>=0).length; if(n<2){gap+=OPPW[j]; if(n===0)zero++;} }
    if(!best||s>best.s) best={s,g,gap:gap/tw*100,zero}; }
  return best;
}
for(const [f,src] of [['11_teams_pool100.csv','nash_full.json'],['12_teams_pool50.csv','nash100.json'],['12b_teams_obs.csv','nash_obs.json']]){
  const NS=JSON.parse(fs.readFileSync(src,'utf8'));
  csv(f,['nash_value','stones','mega_slot','effective_roster_R','mirror_exposure','gap_exposure_pct','zero_answer_opps','members','pick_rates_pct'],
    NS.map(r=>{ const T=r.team.map(k=>idxK[k]); const dg=teamDiag(T);
      return [r.v,r.stones,dg.g<0?'':D[dg.g].ko,r.R,r.EW,dg.gap.toFixed(1),dg.zero,r.team.join('|'),
      r.use.map(x=>Math.round(x/r.use.reduce((a,b)=>a+b,0)*300)).join('|')]; }));
}
/* 7b) 기술 추천 (setopt.mjs → sets_blocks.json) */
const SETS=JSON.parse(fs.readFileSync('sets_blocks.json','utf8'));
{ const rows=[];
  for(const [k,r] of Object.entries(SETS)){ if(!r.moves){ rows.push([k,'','','','','','','','','','',r.skip||'']); continue; }
    const st=m=>m.res?'유지':m.fix?'고정':r.real.some(x=>x.mv===m.mv)?'선택':'바꿈';
    r.moves.forEach((m,x)=>rows.push([k,r.inv,r.mega?1:0,x+1,m.mv,m.ty,m.c,m.p,m.r||'',st(m),m.drop?m.drop.d:'',m.drop?(m.drop.alt||''):'',m.best,r.s,r.realS,r.real.map(q=>q.mv).join('|'),r.alt?r.alt.set.join('|'):'',r.win,r.lose]));
  }
  csv('15_set_recommend.csv',['pokemon','invest','mega','slot','move','type','cat','adoption_pct','role','status','drop_if_replaced','best_replacement','fastest_ko_share_pct','set_score','real_top4_score','real_top4','alt_set','win_share_pct','lose_share_pct'],rows);
}
/* 7c) 종별 실효 메가 확률 */
csv('16_eff_mega.csv',['pokemon','rank','stone_rate_pct','eff_mega_pct','opp_weight_pct'],
  D.map((d,i)=>[d.ko,d.rank,MG[d.ko]?(RATE[d.ko]??''):'',(EFF[i]*100).toFixed(1),OPPW[i].toFixed(3)]));
/* 8) 행렬 CSV */
const mat=(f,fn)=>{
  const head=['atk\\def',...D.map(d=>d.ko)];
  const rr=D.map((m,i)=>[m.ko,...D.map((_,j)=>i===j?0:fn(i,j))]);
  fs.writeFileSync(O+'matrix/'+f,'﻿'+[head.join(','),...rr.map(r=>r.join(','))].join('\n'));
};
mat('V_base.csv',(i,j)=>value(i,j,0,0).toFixed(4));
mat('V_atk_mega.csv',(i,j)=>MG[D[i].ko]?value(i,j,1,0).toFixed(4):'');
mat('V_def_item.csv',(i,j)=>value(i,j,0,0,0,OPPIT[j]).toFixed(4));
mat('TTK.csv',(i,j)=>ttk(i,j,0,0).toFixed(3));
mat('V_def_mega.csv',(i,j)=>MG[D[j].ko]?value(i,j,0,1).toFixed(4):'');
mat('V_both_mega.csv',(i,j)=>(MG[D[i].ko]&&MG[D[j].ko])?value(i,j,1,1).toFixed(4):'');
mat('V_blend_oppmega.csv',(i,j)=>mv0(i,j,-1).toFixed(4));
console.log('CSV/행렬 생성 완료');
