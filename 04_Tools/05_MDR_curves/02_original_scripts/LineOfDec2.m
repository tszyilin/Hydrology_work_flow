function [x,n]=LineOfDec2(fid0)

% function LINEOFDEC extracts decimal data from an ascii string with
% individual data seperated by whitespace, commas colons etc
% Build 2 strips everything to right of %

% Build 002 wjc Meynink 19 jun 05
% mod of LineOfDec
% last mod wjcm 19 jun 05 @ 1442


n=-1;
x(1)=-1;
%k(1)=1
a=[];
numdatflag=0;;
while size(a)==0 | numdatflag==0;
    a=fgetl(fid0);
    k=findstr('%',a);
    if k>0
        a=a(1:k-1);
    end
    if size(a)>0;
        x=double(a);
        y=x>47 & x<58;
        numdatflag=sum(y);
    end
end
        
    
if upper(a(1))~='C'
    a=[a ' '];
    t=double(a);
    l2=size(t);
    k=l2(2);

    for i=1:k
        d(i)=DecNum(t(i));
    end

    numflag=0;
    j=0;
    
    for i=1:k
        if d(i)==1
            if numflag==0
                j=j+1;
                numflag=1;
                startnum=i;
            end % if
        else
            if numflag==1
               endnum=i-1;
               numflag=0;
               %a(startnum:endnum)
               %pause
               x(j)=str2num(a(startnum:endnum));
            end % if
        end % if
    end % for i
    n=j;
end % if