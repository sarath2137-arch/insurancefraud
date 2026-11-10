export const user=()=>JSON.parse(localStorage.getItem('user')||'null');export const logout=()=>{localStorage.clear();location.href='/login'};
