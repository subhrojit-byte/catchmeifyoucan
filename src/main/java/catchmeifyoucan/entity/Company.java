package catchmeifyoucan.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

import java.time.LocalDate;

@Getter
@Entity
@Table(name = "companies")
public class Company {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @Column(nullable = false)
    private String companyName;

    @Setter
    private String registrationNumber;

    @Setter
    private String industry;

    @Setter
    private String address;

    @Setter
    private Integer ageInYears;

    @Setter
    @Column(precision = 19, scale = 2)
    private BigDecimal annualRevenue;

    @Setter
    private Integer numberOfEmployees;

    @Setter
    private LocalDate registrationDate;

    @Setter
    private Boolean shellCompany;

    public Company() {
    }

    public Company(String companyName,
                   String registrationNumber,
                   String industry,
                   String address,
                   Integer ageInYears,
                   BigDecimal annualRevenue,
                   Integer numberOfEmployees,
                   LocalDate registrationDate,
                   Boolean shellCompany) {

        this.companyName = companyName;
        this.registrationNumber = registrationNumber;
        this.industry = industry;
        this.address = address;
        this.ageInYears = ageInYears;
        this.annualRevenue = annualRevenue;
        this.numberOfEmployees = numberOfEmployees;
        this.registrationDate=registrationDate;
        this.shellCompany = shellCompany;
    }

}