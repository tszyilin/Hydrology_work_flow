function [Fmat]=DecFormat(x,FieldW,Lsp,Tsp)

% Function DECFORMAT establishes a format specification so as to maximize
% displayed resolution for prescribed constraints.

% Build 001 wjc meynink 30 April 2003
% mod wjcm 30/4/03 @ 1350
% mod wjcm 02/5/03 @ 1250
% last mod wjcm 13/10/04 @ @1330
%
% VARIABLES LIST
%
% x          - decimal number to be formatted
% FieldW     - Total field width including leading & trailing spaces
% Lsp        - Leading Spaces
% Tsp        - Trailing spaces
% fmat     - Constructed format string

NetField=FieldW-Lsp-Tsp;
if abs(x)>=1;
    IntW=ceil(log10(abs(x)+.00001));
else
    IntW=0;
end

if x<0 
    IntW=IntW+1;
end

DecW=NetField-IntW-1;

if abs(x)<1;
    DecW=DecW-1;
end

if DecW<=0;
    DecW=0;
    Tsp=Tsp+1;
end



if Lsp>0;
    Fmat=' ';
    for j=2:Lsp;
        Fmat=[Fmat ' '];
    end
else
    Fmat='';
end


Fmat=[Fmat '%' num2str(IntW) '.' num2str(DecW) 'f'];
nn=FieldW-Lsp-Tsp-IntW-DecW;
if IntW==0;, nn=nn-1;, end

if DecW==0;,nn=nn+1;,end

for j=1:Tsp+nn;
    Fmat=[Fmat ' '];
end

