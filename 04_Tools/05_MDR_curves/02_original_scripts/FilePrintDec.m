function [status]=FilePrintDec(fid,x,FieldW,Lsp,Tsp,CRLFflag)

% function prints individual number to a file using fixed field format
%
% Build 01 wjcm 11 aug 03
% last mod wjcm 11/8/03 1310h

% VARIABLES LIST
%
% fid  - file ID
% x    - decimal number to be printed to file
% FieldW - total field width including leading and trailing spaces
% Lsp    - # leading(blank) spaces
% Tsp    - # trailing spaces
% CRLFflag - 0=none; 1=new line; 2= CR LF

status='OK';
[Fmat]=DecFormat(x,FieldW,Lsp,Tsp);

if CRLFflag>0
    switch CRLFflag;
        case 1
            Fmat=[Fmat '\n'];
        case 2
            Fmat=[Fmat '\r\n'];
        otherwise
            status='NOK';
    end
end
fprintf(fid,Fmat,x);