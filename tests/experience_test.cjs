const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root=require('path').resolve(__dirname,'../dist'),content=JSON.parse(fs.readFileSync(root+'/assets/question-bank.json'));
const elements=new Map();function el(s){if(!elements.has(s))elements.set(s,{value:'',innerHTML:'',textContent:'',hidden:false,addEventListener(){},classList:{toggle(){},add(){},remove(){}},scrollIntoView(){}});return elements.get(s)}
const ctx={document:{querySelector:el,querySelectorAll:()=>[],documentElement:{},body:{dataset:{role:'student'}}},window:{},localStorage:{getItem(){return 'en'},setItem(){}},setTimeout(){},clearTimeout(){},console,URLSearchParams,fetch:async()=>{throw Error('Unexpected network request in rendering test')}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(root+'/classroom/classroom.js','utf8'),ctx);vm.runInContext(fs.readFileSync(root+'/classroom/experience.js','utf8').replace(/boot\(\);\s*$/,''),ctx);
const run=s=>vm.runInContext(s,ctx);ctx.testUnits=content.units;
run("units=testUnits;me={name:'Test <script>',role:'student',email:''};assignments=[];renderStudentOverview()");
assert(!el('#app').innerHTML.includes('NaN'));assert(el('#app').innerHTML.includes('No evidence yet'));assert(!el('#app').innerHTML.includes('Test <script>'));assert.equal((el('#app').innerHTML.match(/data-skill=/g)||[]).length,6);
ctx.example=[{submitted:100,result:{score:0,total:1,details:[{unit:'third-person',correct:false}]}},{submitted:200,result:{score:1,total:1,details:[{unit:'third-person',correct:true}]}}];
assert.equal(run("evidence(example)['third-person'].correct"),1);assert.equal(run('metrics(example).accuracy'),50);assert.equal(run('metrics([]).accuracy'),null);
run('assignments=example;view="map";renderStudentMap()');assert(el('#app').innerHTML.includes('Latest answers by rule'));assert.equal((el('#app').innerHTML.match(/has-evidence/g)||[]).length,1);
run("me={name:'Teacher',role:'teacher'};classes=[{name:'7A',student_count:2}];results=[];assignments=[];view='overview';renderOverview()");assert(el('#app').innerHTML.includes('Waiting for the first submission'));assert(el('#app').innerHTML.includes('Students'));
for(const role of ['student','teacher']){const html=fs.readFileSync(root+'/classroom/'+role+'.html','utf8');assert(html.includes('data-role="'+role+'"'));assert(html.includes('experience.js'))}
console.log('PASS: empty states, real-only metrics, latest-rule evidence, six skill groups, escaped names and separate role entry pages.');
