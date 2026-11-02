function result = IsLeapYear(yr)
    result = (mod(yr,4) == 0 && mod(yr,100) ~= 0) || (mod(yr,400) == 0);
end