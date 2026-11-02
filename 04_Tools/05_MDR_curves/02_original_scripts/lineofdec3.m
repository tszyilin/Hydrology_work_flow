function [x,n]=LineOfDec(a)

% function LINEOFDEC extracts decimal data from an ascii string with
% individual data seperated by whitespace, commas colons etc

% Build 001 wjc Meynink 9 Mar 03
% mod wjcm 27 Apr 03
% last mod twm 22 Oct 04 @ 1142


n=-1;
x(1)=-1;

if size(a)==0, return; end

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