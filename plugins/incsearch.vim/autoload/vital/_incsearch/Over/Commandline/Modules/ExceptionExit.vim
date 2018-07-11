" ___vital___
" NOTE: lines between '" ___vital___' is generated by :Vitalize.
" Do not mofidify the code nor insert new lines before '" ___vital___'
function! s:_SID() abort
  return matchstr(expand('<sfile>'), '<SNR>\zs\d\+\ze__SID$')
endfunction
execute join(['function! vital#_incsearch#Over#Commandline#Modules#ExceptionExit#import() abort', printf("return map({'make': ''}, \"vital#_incsearch#function('<SNR>%s_' . v:key)\")", s:_SID()), 'endfunction'], "\n")
delfunction s:_SID
" ___vital___
scriptencoding utf-8
let s:save_cpo = &cpo
set cpo&vim

let s:module = {
\	"name" : "ExceptionExit",
\}


function! s:module.on_exception(cmdline)
	call a:cmdline.exit(-1)
endfunction


function! s:make(...)
	let result = deepcopy(s:module)
	let result.exit_code = get(a:, 1, 0)
	return result
endfunction

let &cpo = s:save_cpo
unlet s:save_cpo
