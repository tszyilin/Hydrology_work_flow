function [d]=DecNum(asciicode)

% function determines if asciicode is part of decimal number
d=0;
if asciicode>=43 & asciicode<=57;
    if asciicode~=44 & asciicode~=47;
        d=1;
    end
end