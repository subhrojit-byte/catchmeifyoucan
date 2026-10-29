package catchmeifyoucan.dto;

import catchmeifyoucan.entity.Company;
import lombok.Getter;

import java.math.BigDecimal;
import java.time.LocalDate;

@Getter
public class CompanyObservationResponse {
    private final Long id;
    private final String companyName;
    private final String registrationNumber;
    private final String industry;
    private final String address;
    private final Integer ageInYears;
    private final LocalDate registrationDate;
    private final BigDecimal annualRevenue;
    private final Integer numberOfEmployees;

    public CompanyObservationResponse(Company company) {
        this.id = company.getId();
        this.companyName = company.getCompanyName();
        this.registrationNumber = company.getRegistrationNumber();
        this.industry = company.getIndustry();
        this.address = company.getAddress();
        this.ageInYears = company.getAgeInYears();
        this.registrationDate = company.getRegistrationDate();
        this.annualRevenue = company.getAnnualRevenue();
        this.numberOfEmployees = company.getNumberOfEmployees();
    }
}
