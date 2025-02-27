<?xml version='1.0' encoding='UTF-8'?>
<esdl:EnergySystem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:esdl="http://www.tno.nl/esdl" name="KPI_calc_test_model" id="19d149ac-140e-465a-a76b-2be3297983ea" description="ESDL model to test the KPI calculator" esdlVersion="v2104" version="8">
  <energySystemInformation xsi:type="esdl:EnergySystemInformation" id="3bbbc71e-4d39-41ac-af75-599384b541a2">
    <carriers xsi:type="esdl:Carriers" id="9558d170-44b0-437e-a3a4-ad54938aa6c1">
      <carrier xsi:type="esdl:EnergyCarrier" emission="20.0" name="Gas" id="379bf843-0c15-422a-a861-25aceb2b15c4">
        <emissionUnit xsi:type="esdl:QuantityAndUnitType" id="f1590f3f-fc35-42d9-8e5a-9cb44cc8882b" perUnit="JOULE" perMultiplier="GIGA" physicalQuantity="EMISSION" multiplier="KILO" unit="GRAM"/>
        <energyContentUnit xsi:type="esdl:QuantityAndUnitType" physicalQuantity="ENERGY" id="23ff90ad-be53-453c-b051-379e2b926168"/>
      </carrier>
      <carrier xsi:type="esdl:EnergyCarrier" emission="25.8" name="Biomassa" id="789758ae-ba13-4d59-b3c1-e3c8ecbd4cbb">
        <emissionUnit xsi:type="esdl:QuantityAndUnitType" id="5b7f49a0-9d0a-45b3-9bfc-435b4cdfaf57" perUnit="JOULE" perMultiplier="GIGA" physicalQuantity="EMISSION" multiplier="KILO" unit="GRAM"/>
        <energyContentUnit xsi:type="esdl:QuantityAndUnitType" physicalQuantity="ENERGY" id="6df9215d-ccd1-4517-a2a4-3cf6009fa6cb"/>
      </carrier>
    </carriers>
  </energySystemInformation>
  <instance xsi:type="esdl:Instance" id="1441ce92-1828-4276-b9bf-5c9c28c78e47" name="Untitled instance">
    <area xsi:type="esdl:Area" id="d41536ac-11cc-4db9-81ca-92b81cc42d96" name="KPI_test">
      <asset xsi:type="esdl:GenericConsumer" technicalLifetime="5.0" name="GenericConsumer_a524" id="a5243809-0077-46e5-a0ea-09aa486f5e96">
        <geometry xsi:type="esdl:Point" lon="4.367194175720216" lat="52.071065406906634" CRS="WGS84"/>
        <port xsi:type="esdl:InPort" id="4ddf1d8f-7633-4486-bd56-0ef9c2d6c274" name="In"/>
        <port xsi:type="esdl:OutPort" id="3b1a370f-7c52-499b-a097-758ab4e4b5db" name="Out"/>
        <costInformation xsi:type="esdl:CostInformation" id="c2da9c0c-d8a5-4d21-b6f5-95bfb6026a94">
          <variableOperationalCosts xsi:type="esdl:SingleValue" id="97ff0287-f77f-48cc-9827-80f68cbb589a">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="b1df0c23-8927-489a-8aac-ccd3bbff5412" description="Cost in EUR/kW" perUnit="WATT" perMultiplier="KILO" physicalQuantity="COST" unit="EURO"/>
          </variableOperationalCosts>
          <installationCosts xsi:type="esdl:SingleValue" value="100.0" id="21b68fc1-8c8d-4d4f-b9a2-d965094ab435">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="96d03562-6bd8-4fc0-a211-91e2922232d3" physicalQuantity="COST" description="Cost in EUR" unit="EURO"/>
          </installationCosts>
          <variableMaintenanceCosts xsi:type="esdl:SingleValue" id="6cf2fd73-5f48-4f7f-b333-1f9613e73cda">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="cf053486-a226-4c8e-821b-cc8d760c7b9b" description="Cost in EUR/kW" perUnit="WATT" perMultiplier="KILO" physicalQuantity="COST" unit="EURO"/>
          </variableMaintenanceCosts>
          <investmentCosts xsi:type="esdl:SingleValue" value="1000.0" id="d73f8937-e440-4503-9c12-4b9cab84fd7d">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="2faaa0a5-5ae3-4819-9e7c-af1af1dd24f9" physicalQuantity="COST" description="Cost in EUR" unit="EURO"/>
          </investmentCosts>
          <fixedOperationalCosts xsi:type="esdl:SingleValue" value="3.0" id="ed80763e-1552-4a73-afd8-ebd3e3ff1044">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="e5dab372-d805-4233-870e-457c349caf65" physicalQuantity="COST" description="Cost in %" unit="PERCENT"/>
          </fixedOperationalCosts>
          <fixedMaintenanceCosts xsi:type="esdl:SingleValue" value="2.0" id="380de87f-6336-4942-8a0e-70204380bfbd">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="91ad1572-02a5-4254-ab90-c87be7e92745" physicalQuantity="COST" description="Cost in %" unit="PERCENT"/>
          </fixedMaintenanceCosts>
        </costInformation>
      </asset>
      <asset xsi:type="esdl:GasHeater" technicalLifetime="15.0" name="GasHeater_743b" id="743b1ff1-0ee4-4c6c-ba5f-e7ebf169348c">
        <geometry xsi:type="esdl:Point" lon="4.370026588439942" lat="52.07003660006025" CRS="WGS84"/>
        <port xsi:type="esdl:InPort" id="fff59e3d-19c9-4b59-84af-5537973fb3f0" name="In"/>
        <port xsi:type="esdl:OutPort" id="9589882f-b811-4292-933f-ae658d068a33" name="Out"/>
        <port xsi:type="esdl:InPort" id="292387d2-d347-41e0-af47-b305d1bfaea3" carrier="379bf843-0c15-422a-a861-25aceb2b15c4" name="gasin"/>
        <costInformation xsi:type="esdl:CostInformation" id="76723069-4692-4b00-86fb-d083cadd21c3">
          <variableOperationalCosts xsi:type="esdl:SingleValue" value="0.1" id="e1d7a3b3-d20e-49a8-9caa-b79399760f2e">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="417b012b-d902-4319-9c83-55a8fa2f4f3d" description="Cost in EUR/kWh" perUnit="WATTHOUR" perMultiplier="KILO" physicalQuantity="COST" unit="EURO"/>
          </variableOperationalCosts>
          <installationCosts xsi:type="esdl:SingleValue" value="200.0" id="569c2977-64c4-44ed-8c6f-af5e8bd29a01">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="fada3da3-a180-4450-8c7d-7271f2dd01fc" physicalQuantity="COST" description="Cost in EUR" unit="EURO"/>
          </installationCosts>
          <variableMaintenanceCosts xsi:type="esdl:SingleValue" value="0.2" id="db58dc65-4dae-462a-927a-438c05c0f4c2">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="52fa6923-be78-49a7-af7c-95220175cd64" description="Cost in EUR/kWh" perUnit="WATTHOUR" perMultiplier="KILO" physicalQuantity="COST" unit="EURO"/>
          </variableMaintenanceCosts>
          <investmentCosts xsi:type="esdl:SingleValue" value="2000.0" id="464fbaea-2d8c-42c4-9e53-f8743d33663c">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="f18e476d-08b4-4baa-ab3e-0ead4e7d6365" physicalQuantity="COST" description="Cost in EUR" unit="EURO"/>
          </investmentCosts>
          <fixedOperationalCosts xsi:type="esdl:SingleValue" value="2.0" id="bdf4f59b-3eae-4397-ad1d-f2a038d319b2">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="3087ab78-6536-426b-9d20-c7e7469e7c13" physicalQuantity="COST" description="Cost in %" unit="PERCENT"/>
          </fixedOperationalCosts>
          <fixedMaintenanceCosts xsi:type="esdl:SingleValue" value="1.0" id="445bb14d-66ca-4d6a-a8f8-5182d2718ef5">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="e9693fbb-5207-4042-adae-f4f41c07a123" physicalQuantity="COST" description="Cost in %" unit="PERCENT"/>
          </fixedMaintenanceCosts>
        </costInformation>
      </asset>
      <asset xsi:type="esdl:GenericProducer" technicalLifetime="20.0" name="GenericProducer_b986" id="b98655e1-9e81-4878-875f-c1f946cc5d6c">
        <geometry xsi:type="esdl:Point" lon="4.371528625488282" lat="52.071210493144434" CRS="WGS84"/>
        <port xsi:type="esdl:OutPort" id="4fd8fb51-f919-4abc-8ab2-88f91eb42036" name="Out"/>
        <port xsi:type="esdl:InPort" id="4402a9a2-7e39-4606-868e-c342bb4480e1" name="In"/>
        <port xsi:type="esdl:InPort" id="c1a57afd-d9a1-4753-9003-e85b82de6e60" carrier="789758ae-ba13-4d59-b3c1-e3c8ecbd4cbb" name="Energy"/>
        <costInformation xsi:type="esdl:CostInformation" id="312bf9c4-8dc3-4eea-ab10-4ef7c229a602">
          <variableOperationalCosts xsi:type="esdl:SingleValue" value="2.0" id="6b6022e8-a343-4934-9e4e-e4afe0d19a2c">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="d7b03c29-5fe8-469f-85b0-bd96d3a54f8c" description="Cost in EUR/kWh" perUnit="WATTHOUR" perMultiplier="KILO" physicalQuantity="COST" unit="EURO"/>
          </variableOperationalCosts>
          <installationCosts xsi:type="esdl:SingleValue" value="1500.0" id="e95235fb-286d-4f47-be4c-811e036b8041">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="885f5734-a8b6-4be2-bf69-e7d691268361" physicalQuantity="COST" description="Cost in EUR" unit="EURO"/>
          </installationCosts>
          <variableMaintenanceCosts xsi:type="esdl:SingleValue" value="3.0" id="edb520b1-0eed-4d0e-8b7c-43d38304e55d">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="3edcf9bb-5b62-4c25-9ff3-fc0d5a4291a4" description="Cost in EUR/MWh" perUnit="WATTHOUR" perMultiplier="MEGA" physicalQuantity="COST" unit="EURO"/>
          </variableMaintenanceCosts>
          <investmentCosts xsi:type="esdl:SingleValue" value="3000.0" id="57444f95-c7b1-46bf-8c85-7aec61c762f5">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="30f3c57d-a13c-4970-927a-65419ac6dfb6" physicalQuantity="COST" description="Cost in EUR" unit="EURO"/>
          </investmentCosts>
          <fixedOperationalCosts xsi:type="esdl:SingleValue" value="200.0" id="50148c1d-1b98-45c3-b0b3-330b47b1bc8a">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="347e47f5-0830-4a0d-9a49-59de4a44dbbc" description="Cost in EUR/yr" perTimeUnit="YEAR" physicalQuantity="COST" unit="EURO"/>
          </fixedOperationalCosts>
          <fixedMaintenanceCosts xsi:type="esdl:SingleValue" value="300.0" id="0b76178e-12ca-4cad-92d9-415ca75c104a">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="46a0ab28-9339-44a1-84b5-c5c8c334fb05" description="Cost in EUR/yr" perTimeUnit="YEAR" physicalQuantity="COST" unit="EURO"/>
          </fixedMaintenanceCosts>
        </costInformation>
      </asset>
      <asset xsi:type="esdl:HeatStorage" name="HeatStorage_2a36" id="2a36abb1-0bc0-47fd-b7b1-869118b228fc">
        <geometry xsi:type="esdl:Point" lon="4.368674755096436" lat="52.06920562337898" CRS="WGS84"/>
        <port xsi:type="esdl:InPort" id="05fb032d-90d7-4068-9ca5-015fdafb8caa" name="In"/>
        <port xsi:type="esdl:OutPort" id="5f345f86-3873-4265-84ba-f696c1f7dd45" name="Out"/>
        <costInformation xsi:type="esdl:CostInformation" id="cd8e813b-6c89-43f5-be0c-712afbf400c9">
          <variableOperationalCosts xsi:type="esdl:SingleValue" id="accd21df-018f-47aa-8c23-efb96815155a">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="7af953db-667e-4b49-bf04-30e5d8b9740a" physicalQuantity="COST" description="Cost in %" unit="PERCENT"/>
          </variableOperationalCosts>
          <installationCosts xsi:type="esdl:SingleValue" value="600.0" id="322d9a2f-083d-492a-95b9-213b6b63fdb6">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="37ed0f6d-79f3-430a-8a15-a19b2426ac64" description="Cost in EUR/yr" perTimeUnit="YEAR" physicalQuantity="COST" unit="EURO"/>
          </installationCosts>
          <investmentCosts xsi:type="esdl:SingleValue" value="500.0" id="6d220497-2747-4e8c-ab9b-36fb3eb739a7">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="431ad224-033a-4e64-a0fc-2e931ef0bb69" description="Cost in EUR/yr" perTimeUnit="YEAR" physicalQuantity="COST" unit="EURO"/>
          </investmentCosts>
          <fixedOperationalCosts xsi:type="esdl:SingleValue" value="5.0" id="ba5b8c4f-39b7-4068-9490-4601bedae930">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="51984204-1eea-42e5-8671-3ec9c9af7643" physicalQuantity="COST" description="Cost in %" unit="PERCENT"/>
          </fixedOperationalCosts>
          <fixedMaintenanceCosts xsi:type="esdl:SingleValue" value="1.0" id="7fe1f4b7-765a-4d76-80b1-d7e5e7e58f06">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="c312175c-da68-4080-8ad5-148db6790776" physicalQuantity="COST" description="Cost in %" unit="PERCENT"/>
          </fixedMaintenanceCosts>
        </costInformation>
      </asset>
      <asset xsi:type="esdl:Pipe" name="Pipe_a259" length="1000.0" id="a25970c8-80c8-461e-b58d-ed7f0f792115">
        <geometry xsi:type="esdl:Line" CRS="WGS84">
          <point xsi:type="esdl:Point" lat="52.07239754465432" lon="4.3724942207336435"/>
          <point xsi:type="esdl:Point" lat="52.07423081775409" lon="4.375884532928468"/>
          <point xsi:type="esdl:Point" lat="52.06898138892661" lon="4.381334781646729"/>
        </geometry>
        <port xsi:type="esdl:InPort" id="98f7eb27-d873-49fa-b8ff-6f3a52bfca85" name="In"/>
        <port xsi:type="esdl:OutPort" id="c0e1a6d5-9474-4614-babb-bc5aeab6903e" name="Out"/>
        <costInformation xsi:type="esdl:CostInformation" id="12a2a04d-17ce-4c92-b607-56727447211c">
          <investmentCosts xsi:type="esdl:SingleValue" value="100.0" id="b0608caa-e03f-40a0-a962-a1d66e368a4b">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="f20bc698-5700-4022-8162-75655488584f" description="Cost in EUR/m" perUnit="METRE" physicalQuantity="COST" unit="EURO"/>
          </investmentCosts>
          <installationCosts xsi:type="esdl:SingleValue" value="0.1" id="c44021eb-c510-4926-839d-e1bb3f8940ee">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="d082d691-9bcf-485c-8e50-2c04413e1eb9" description="Cost in EUR/km" perUnit="METRE" perMultiplier="KILO" physicalQuantity="COST" unit="EURO"/>
          </installationCosts>
        </costInformation>
      </asset>
      <asset xsi:type="esdl:GeothermalSource" power="30.0" technicalLifetime="15.0" name="GeothermalSource_b230" id="b230a081-0c8d-4f95-9cc7-6548f33bf513" COP="10.0">
        <geometry xsi:type="esdl:Point" lon="4.373180866241456" CRS="WGS84" lat="52.069906063789766"/>
        <port xsi:type="esdl:OutPort" id="0d79e20d-9bcc-4206-b9b0-5c4d31e13565" name="Out"/>
        <port xsi:type="esdl:InPort" id="7209ec2f-30c3-45d1-b630-422cd8340899" name="In"/>
        <costInformation xsi:type="esdl:CostInformation" id="c607f9d5-62bb-4d3f-88a4-4d7769ef23c7">
          <variableOperationalCosts xsi:type="esdl:SingleValue" value="10.0" id="30e3d9fb-861f-4795-91b4-0cabe5eba47c">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="65146e7c-85f9-478f-a3e3-3b9d70cfed58" description="Cost in EUR/MW" perUnit="WATT" perMultiplier="MEGA" physicalQuantity="COST" unit="EURO"/>
          </variableOperationalCosts>
          <installationCosts xsi:type="esdl:SingleValue" value="20.0" id="998ef613-7ffb-4f62-9c2e-b8116aede8f6">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="f9a3ccf3-1621-4c40-af54-455a944291ce" description="Cost in EUR/MW" perUnit="WATT" perMultiplier="MEGA" physicalQuantity="COST" unit="EURO"/>
          </installationCosts>
          <investmentCosts xsi:type="esdl:SingleValue" value="1000.0" id="e21db9ce-11f3-4175-a621-2840b609c903">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="6b304b75-4f62-489a-b44a-f165d3313590" description="Cost in EUR/MW" perUnit="WATT" perMultiplier="MEGA" physicalQuantity="COST" unit="EURO"/>
          </investmentCosts>
          <variableMaintenanceCosts xsi:type="esdl:SingleValue" value="20.0" id="65080ce5-b126-4cb5-bcdb-dcde09800fa8">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="79bafad5-b2b0-429f-92d8-0fed18e5fe7f" description="Cost in EUR/MW" perUnit="WATT" perMultiplier="MEGA" physicalQuantity="COST" unit="EURO"/>
          </variableMaintenanceCosts>
          <fixedOperationalCosts xsi:type="esdl:SingleValue" value="3000.0" id="4acc4e7d-463b-40eb-a34e-13d0c17168b6">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="b508b3a5-af63-4059-8f7e-4958c23cac53" description="Cost in EUR/yr" perTimeUnit="YEAR" physicalQuantity="COST" unit="EURO"/>
          </fixedOperationalCosts>
          <fixedMaintenanceCosts xsi:type="esdl:SingleValue" value="2000.0" id="4172e759-0edf-4af6-a8ef-b7922dfd48fc">
            <profileQuantityAndUnit xsi:type="esdl:QuantityAndUnitType" id="4d5d339d-512d-4855-b0a1-e95c3219641a" description="Cost in EUR/yr" perTimeUnit="YEAR" physicalQuantity="COST" unit="EURO"/>
          </fixedMaintenanceCosts>
        </costInformation>
      </asset>
    </area>
  </instance>
</esdl:EnergySystem>
