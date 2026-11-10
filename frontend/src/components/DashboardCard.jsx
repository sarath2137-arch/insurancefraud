export default function DashboardCard({label,value,accent='blue'}){return <article className={'card '+accent}><small>{label}</small><strong>{value}</strong></article>}
