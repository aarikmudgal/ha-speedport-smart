import assert from "node:assert/strict";
import test from "node:test";
import {File} from "node:buffer";
import {bindFileTransferEditor, createFileTransferEditorController, renderFileTransferEditor} from "../../custom_components/speedport_smart/frontend/file-transfer-editor.js";

const UPLOAD = {id:"system_firmware_upload", title:"Upload firmware", execution_policy:"file_transfer", direction:"upload", maximum_bytes:1024, confirmation:"UPLOAD FIRMWARE", warning:"Router may restart.", supported:true};
const DOWNLOAD = {...UPLOAD, id:"system_backup_download", direction:"download", confirmation:"DOWNLOAD PRIVATE BACKUP", password:{label:"Password"}};
const grant = (action) => ({action:action.id, grant:"a".repeat(64), expires_in:120});
const json = (value, status=200) => new Response(JSON.stringify(value), {status,headers:{"content-type":"application/json"}});
const ready = (controller, action=UPLOAD) => {
  controller.open({entryId:"entry-a",action});
  if(action.direction==="upload") controller.setFile(new File(["firmware"],"firmware.bin"));
  controller.setConfirmation(action.confirmation);
};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test("open, render, file selection and unconfirmed click perform no requests",async()=>{
  let calls=0;const c=createFileTransferEditorController({request:async()=>calls++});
  ready(c);renderFileTransferEditor(c);assert.equal(await c.execute(),false);
  assert.equal(calls,0);assert.equal(c.snapshot().status,"invalid");
});
test("hash, prepare and exact multipart execute run once; private drafts clear",async()=>{
  const calls=[];let multipart;
  const c=createFileTransferEditorController({digest:async()=>"b".repeat(64),request:async(path,options)=>{
    if(path.endsWith("prepare")){calls.push([path,JSON.parse(options.body)]);return json(grant(UPLOAD));}
    multipart=options.body;calls.push([path,JSON.parse(multipart.get("metadata")),multipart.get("file").name]);
    return json({action:UPLOAD.id,result:{status:"processing"}});
  }});
  ready(c);assert.equal(await c.execute(),true);assert.equal(await c.execute(),false);
  assert.equal(calls.length,2);assert.deepEqual(calls[0][1],{action:UPLOAD.id,size:8,sha256:"b".repeat(64),confirmed:true,confirmation_text:UPLOAD.confirmation});
  assert.equal(calls[1][2],"firmware.bin");assert.equal(multipart.get("metadata"),null);assert.equal(multipart.get("file"),null);
  assert.equal(c.snapshot().status,"processing");assert.equal(c.snapshot().filename,"");
});
test("download accepts bounded binary and fixed filename only",async()=>{
  const downloads=[];let metadata;
  const c=createFileTransferEditorController({request:async(path,options)=>{
    if(path.endsWith("prepare")){const body=JSON.parse(options.body);assert.equal(body.size,0);assert.equal(body.sha256,null);return json(grant(DOWNLOAD));}
    metadata=JSON.parse(options.body.get("metadata"));
    return new Response("private-backup",{headers:{"content-type":"application/octet-stream","content-disposition":"attachment; filename=unsafe.html"}});
  },download:async(blob,name)=>downloads.push([blob.size,name])});
  ready(c,DOWNLOAD);c.setPassword("PRIVATE-PASSWORD");assert.doesNotMatch(JSON.stringify(c.snapshot()),/PRIVATE-PASSWORD/);
  assert.equal(await c.execute(),true);assert.equal(metadata.password,"PRIVATE-PASSWORD");
  assert.deepEqual(downloads,[[14,"speedport-configuration-backup.bin"]]);assert.equal(c.snapshot().status,"downloaded");
});
test("navigation while preparing prevents execute; duplicate clicks and close blocked",async()=>{
  const pending=deferred();let calls=0;const c=createFileTransferEditorController({request:()=>{calls++;return pending.promise;}});
  ready(c,DOWNLOAD);const work=c.execute();assert.equal(await c.execute(),false);assert.equal(c.close(),false);
  c.dispose();pending.resolve(json(grant(DOWNLOAD)));assert.equal(await work,false);assert.equal(calls,1);assert.equal(c.snapshot(),null);
});
test("navigation while hashing prevents prepare",async()=>{
  const pending=deferred();let calls=0;const c=createFileTransferEditorController({digest:()=>pending.promise,request:async()=>calls++});
  ready(c);const work=c.execute();c.dispose();pending.resolve("a".repeat(64));assert.equal(await work,false);assert.equal(calls,0);
});
test("invalid grants, files and hashes stop before transfer",async()=>{
  for(const approval of [{...grant(DOWNLOAD),action:UPLOAD.id},{...grant(DOWNLOAD),grant:"bad"},{...grant(DOWNLOAD),expires_in:0}]){
    let calls=0;const c=createFileTransferEditorController({request:async()=>{calls++;return json(approval);}});
    ready(c,DOWNLOAD);assert.equal(await c.execute(),false);assert.equal(calls,1);
  }
  for(const size of [0,1025]){
    const c=createFileTransferEditorController({request:async()=>assert.fail("no request")});ready(c);
    c.setFile(new File([new Uint8Array(size)],"bad.bin"));assert.equal(await c.execute(),false);
  }
  const c=createFileTransferEditorController({digest:async()=>"bad",request:async()=>assert.fail("no request")});ready(c);assert.equal(await c.execute(),false);
});
test("wrong identity and unexpected success never claim completion",async()=>{
  for(const result of [{action:UPLOAD.id,result:{status:"verified"}},{action:DOWNLOAD.id,result:{status:"processing"}},{action:UPLOAD.id,result:{status:"outcome_unknown"}}]){
    let calls=0;const c=createFileTransferEditorController({digest:async()=>"b".repeat(64),request:async()=>++calls===1?json(grant(UPLOAD)):json(result)});
    ready(c);assert.equal(await c.execute(),false);assert.equal(c.snapshot().status,"outcome_unknown");assert.equal(calls,2);
  }
});
test("transport errors never render private details or retry",async()=>{
  let calls=0;const c=createFileTransferEditorController({request:async()=>{if(++calls===1)return json(grant(DOWNLOAD));throw new Error("PRIVATE-TOKEN");}});
  ready(c,DOWNLOAD);assert.equal(await c.execute(),false);assert.doesNotMatch(renderFileTransferEditor(c),/PRIVATE-TOKEN/);
  assert.equal(c.snapshot().status,"outcome_unknown");assert.equal(await c.execute(),false);assert.equal(calls,2);
});
test("HTML errors and oversized binary backups never download",async()=>{
  for(const response of [new Response("<html>login</html>"),new Response(new Uint8Array(1025),{headers:{"content-type":"application/octet-stream"}})]){
    let calls=0;const c=createFileTransferEditorController({request:async()=>++calls===1?json(grant(DOWNLOAD)):response,download:()=>assert.fail("no download")});
    ready(c,DOWNLOAD);assert.equal(await c.execute(),false);assert.equal(c.snapshot().status,"outcome_unknown");
  }
});
test("renderer escapes labels and follows HA theme; schemas fail closed",()=>{
  const c=createFileTransferEditorController({request:async()=>{}});
  for(const action of [{...UPLOAD,id:"constructor"},{...UPLOAD,supported:false},{...UPLOAD,maximum_bytes:-1}]) assert.throws(()=>c.open({entryId:"entry",action}));
  ready(c,{...UPLOAD,title:"<script>unsafe</script>"});const html=renderFileTransferEditor(c);
  assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);assert.match(html,/var\(--primary-text-color\)/);assert.match(html,/aria-live="polite"/);
});
test("binding disposal clears DOM inputs and private state",()=>{
  const listeners=new Map();const input={value:"PRIVATE"};const root={addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:key=>listeners.delete(key),querySelectorAll:()=>[input]};
  const c=createFileTransferEditorController({request:async()=>{}});ready(c);
  const dispose=bindFileTransferEditor(root,c);assert.equal(listeners.size,3);dispose();assert.equal(listeners.size,0);assert.equal(input.value,"");assert.equal(c.snapshot(),null);
});

test("finite native phonebook IDs use fixed private filenames; online aliases rejected",async()=>{
  for(let book=0;book<6;book++){
    const action={...DOWNLOAD,id:`phonebook_export_${book}`,password:null};let calls=0;const files=[];
    const c=createFileTransferEditorController({request:async()=>++calls===1?json(grant(action)):new Response("private CSV",{headers:{"content-type":"application/octet-stream"}}),download:async(blob,name)=>files.push(name)});
    ready(c,action);assert.equal(await c.execute(),true);assert.deepEqual(files,[`speedport-phonebook-${book+1}.csv`]);assert.equal(c.snapshot().status,"phonebook_downloaded");
    assert.match(renderFileTransferEditor(c),/Download phonebook CSV/);
  }
  const c=createFileTransferEditorController({request:async()=>assert.fail("no request")});
  for(const id of ["phonebook_export_6","phonebook_import_100","phonebook_import_00","phonebook_export_-1"])assert.throws(()=>c.open({entryId:"entry",action:{...DOWNLOAD,id}}));
});
test("phonebook import accepts native counters without claiming verified contact count",async()=>{
  const action={...UPLOAD,id:"phonebook_import_2"};let calls=0;
  const c=createFileTransferEditorController({digest:async()=>"a".repeat(64),request:async()=>++calls===1?json(grant(action)):json({action:action.id,result:{status:"import_accepted",router_status:0,verification:"contents_unverified",reported_total:20,reported_ignored:3,reported_full:0,private:"SECRET"}})});
  ready(c,action);assert.equal(await c.execute(),true);assert.equal(c.snapshot().status,"import_accepted");
  const html=renderFileTransferEditor(c);assert.match(html,/Router-reported total: 20/);assert.match(html,/Ignored: 3/);assert.match(html,/not been individually verified/);assert.doesNotMatch(html,/SECRET/);assert.equal(await c.execute(),false);assert.equal(calls,2);
});
test("phonebook empty export and full import have explicit non-mutating preflight errors",async()=>{
  for(const [id,error] of [["phonebook_export_0","phonebook_empty"],["phonebook_import_4","phonebook_full"]]){
    const action={...(id.includes("import")?UPLOAD:DOWNLOAD),id};let calls=0;
    const c=createFileTransferEditorController({digest:async()=>"a".repeat(64),request:async()=>++calls===1?json(grant(action)):json({error},400)});
    ready(c,action);assert.equal(await c.execute(),false);assert.equal(c.snapshot().status,error);assert.equal(calls,2);
  }
});
test("phonebook malformed import counters fail closed and safe rejection explains space",async()=>{
  const action={...UPLOAD,id:"phonebook_import_0"};
  for(const details of [{status:"import_accepted",router_status:0,verification:"contents_unverified",reported_total:1,reported_ignored:2},{status:"import_accepted",router_status:0,verification:"verified",reported_total:1,reported_ignored:0},{status:"rejected",router_status:"SECRET"}]){
    let calls=0;const c=createFileTransferEditorController({digest:async()=>"a".repeat(64),request:async()=>++calls===1?json(grant(action)):json({action:action.id,result:details})});
    ready(c,action);assert.equal(await c.execute(),false);assert.equal(c.snapshot().status,"outcome_unknown");assert.doesNotMatch(renderFileTransferEditor(c),/SECRET/);
  }
  let calls=0;const c=createFileTransferEditorController({digest:async()=>"a".repeat(64),request:async()=>++calls===1?json(grant(action)):json({action:action.id,result:{status:"rejected",router_status:3,reported_full:2}})});
  ready(c,action);assert.equal(await c.execute(),false);assert.match(renderFileTransferEditor(c),/import may be partial/);assert.match(renderFileTransferEditor(c),/full: 2/);
});

test("private log and Router-Pass downloads stay private and use fixed filenames",async()=>{
  for(const [id,filename] of [["system_log_download","speedport-system-log.txt"],["system_router_pass_download","speedport-router-pass.txt"]]){
    const action={...DOWNLOAD,id,password:id.includes("router_pass")?{label:"Optional print password"}:null};
    let calls=0;const files=[];
    const c=createFileTransferEditorController({request:async()=>++calls===1?json(grant(action)):new Response("PRIVATE",{headers:{"content-type":"application/octet-stream"}}),download:async(blob,name)=>files.push(name)});
    ready(c,action);if(action.password)c.setPassword("PRIVATE-ADMIN");
    assert.doesNotMatch(renderFileTransferEditor(c),/PRIVATE-ADMIN/);
    assert.doesNotMatch(JSON.stringify(c.snapshot()),/PRIVATE-ADMIN/);
    c.setConfirmation(action.confirmation);if(action.password)c.setPassword("PRIVATE-ADMIN");
    assert.equal(await c.execute(),true);assert.deepEqual(files,[filename]);assert.equal(c.snapshot().status,"private_downloaded");
    assert.match(renderFileTransferEditor(c),/Download private file/);assert.equal(calls,2);
    assert.equal(await c.execute(),false);
  }
});
