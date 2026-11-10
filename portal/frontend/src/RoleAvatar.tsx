import {BookOpen,Mic,BookHeart,Lightbulb,HeartHandshake,Atom,GraduationCap,Bot} from 'lucide-react'
const themes=[['#2369cc','#e5f0ff',BookOpen],['#7953c7','#f0eaff',Mic],['#c77d25','#fff2d9',BookHeart],['#249879','#e1f7ed',Lightbulb],['#ce578b','#fde9f3',HeartHandshake],['#168ea5','#ddf7fa',Atom],['#5267b0','#e9edff',GraduationCap],['#50687e','#eaf0f5',Bot]] as const
export const avatarNames=['teacher','pronunciation','story','homework','buddy','stem','consultant','general']
export function RoleAvatar({name,roleId}:{name:string;roleId:string}){
 let index=avatarNames.indexOf(name)
 if(index<0){const builtins=['english-teacher','pronunciation','storytelling','homework','buddy','stem','consultant','general'];index=builtins.findIndex(id=>roleId==='builtin-'+id);if(index<0)index=[...roleId].reduce((n,c)=>n+c.charCodeAt(0),0)%8}
 const [color,bg,Icon]=themes[index]
 return <div className="role-art" style={{background:bg,color}}><svg viewBox="0 0 160 120" aria-hidden="true"><path d="M80 14v12m-5-14h10" stroke="currentColor" strokeWidth="5" strokeLinecap="round"/><rect x="29" y="27" width="102" height="76" rx="28" fill="currentColor"/><rect x="39" y="37" width="82" height="52" rx="19" fill="white"/><circle cx="62" cy="60" r="6" fill="currentColor"/><circle cx="98" cy="60" r="6" fill="currentColor"/><path d="M69 74q11 9 22 0" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round"/><path d="M20 53v27m120-27v27" stroke="currentColor" strokeWidth="8" strokeLinecap="round"/></svg><span className="role-art-icon"><Icon size={27}/></span><span className="role-art-brand">WIN</span></div>
}
