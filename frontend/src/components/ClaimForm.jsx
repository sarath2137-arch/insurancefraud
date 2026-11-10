import {useState} from 'react';
import {createClaim} from '../services/claimService';
import {useNavigate} from 'react-router-dom';

const createInitial=()=>({claim_id:`CLM-${globalThis.crypto?.randomUUID?.()||`${Date.now().toString(36)}-${Math.random().toString(36).slice(2,10)}`}`,provider_id:'',patient_reference_id:'',hospital:'',patient_age:'',gender:'',diagnosis:'',treatment_type:'',admission_date:'',discharge_date:'',claim_amount:'',previous_claims:'',previous_claim_amount:'',provider_information:''});
const numberFields=new Set(['patient_age','claim_amount','previous_claims','previous_claim_amount']);

export default function ClaimForm(){
 const [form,setForm]=useState(createInitial),[error,setError]=useState(''),[busy,setBusy]=useState(false),go=useNavigate();
 const submit=async e=>{e.preventDefault();setBusy(true);setError('');try{const {data}=await createClaim({...form,patient_age:+form.patient_age,claim_amount:+form.claim_amount,previous_claims:+form.previous_claims,previous_claim_amount:+form.previous_claim_amount});go('/claims/'+data.claim_id)}catch(e){setError(e.response?.data?.detail||'Unable to submit claim')}finally{setBusy(false)}};
 return <form onSubmit={submit} className="claimform">{error&&<div className="error">{error}</div>}<h2>Claim details</h2><p>Enter the exact Provider ID from the configured provider source data. This is required for provider-level scoring.</p><div className="fields">{Object.entries(form).map(([k,v])=><label key={k}>{k.replaceAll('_',' ')}<input required type={k.includes('date')?'date':numberFields.has(k)?'number':'text'} value={v} onChange={e=>setForm({...form,[k]:e.target.value})}/></label>)}</div><button className="primary" disabled={busy}>{busy?'Analyzing…':'Submit and analyze claim'}</button></form>
}
